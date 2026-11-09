"""Sign-in by email link and by Google, sessions, sign-out and the cross-site request check (VEC-4).

Requests run as the platform database role (`as_role`), not as the superuser tests connect with,
so row-level security on accounts applies as in production. Google is replaced by a fake: the
round trip to Google is not what these tests check, what we do with its answer is.
"""

import hashlib
import logging
import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient
from httpx2 import Response
from sqlalchemy import ColumnElement, delete, func, insert, select, text, update
from sqlalchemy.orm import Session

from app.auth.models import (
    AuthSession,
    AuthUser,
    EmailVerification,
    LinkedAccount,
    PasswordCredential,
    VerificationPurpose,
)
from app.auth.router.email_links import email_sender
from app.auth.router.google import google_client
from app.auth.service import (
    GOOGLE_COOKIE,
    SESSION_COOKIE,
    CurrentUser,
    GoogleAuthorization,
    GoogleProfile,
    GoogleSignInFailed,
    InvalidEmailLink,
    SessionCookieMiddleware,
    get_current_user,
    request_sign_in_link,
    sign_in_with_email_link,
)
from app.auth.service.email_delivery import ConsoleEmailSender
from app.auth.service.google import AuthlibGoogleClient
from app.auth.service.sessions import find_session
from app.auth.service.tokens import new_token
from app.core.config import Settings, get_settings
from app.core.db import AGENT_ROLE, PLATFORM_ROLE, SessionLocal, get_db
from app.core.model_base import Base
from app.documents.models import Account
from app.main import app
from tests.conftest import as_role
from tests.factories import make_account

SETTINGS = get_settings()
ARGON2_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA"


@dataclass
class FakeSender:
    sent: list[tuple[str, str]] = field(default_factory=list)

    def send_sign_in_link(self, email: str, link: str) -> None:
        self.sent.append((email, link))

    def last_token(self) -> str:
        return self.sent[-1][1].split("#token=")[1]


@dataclass
class FakeGoogle:
    profile: GoogleProfile | None = None
    calls: list[tuple[str, str]] = field(default_factory=list)

    def start(self) -> GoogleAuthorization:
        return GoogleAuthorization(
            url="https://accounts.google.com/o/oauth2/v2/auth?state=state-1",
            state="state-1",
            code_verifier="v" * 64,
        )

    def fetch_profile(self, code: str, code_verifier: str) -> GoogleProfile:
        self.calls.append((code, code_verifier))
        if self.profile is None:
            raise GoogleSignInFailed
        return self.profile


@dataclass
class Api:
    client: TestClient
    sender: FakeSender
    google: FakeGoogle


def _browser() -> TestClient:
    """A browser of its own, with its own cookies, talking to the app as the editor does."""
    # https, or the client would not send back the Secure cookies. Origin: what the editor sends.
    return TestClient(
        app,
        base_url="https://testserver",
        headers={"Origin": SETTINGS.frontend_url},
        follow_redirects=False,
    )


@pytest.fixture
def api(db: Session) -> Iterator[Api]:
    as_role(db, PLATFORM_ROLE)
    sender, google = FakeSender(), FakeGoogle()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[email_sender] = lambda: sender
    app.dependency_overrides[google_client] = lambda: google
    try:
        yield Api(_browser(), sender, google)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def ana_account(db: Session) -> Account:
    """Ana's existing account. List it before `api`: it must be created before the role switch."""
    return make_account(db, "ana@example.com")


@pytest.fixture
def luis_account(db: Session) -> Account:
    """Luis's existing account. List it before `api`, like `ana_account`."""
    return make_account(db, "luis@example.com")


def _use_cookie(api: Api, name: str, value: str) -> None:
    # Cleared first: a cookie set by a response and one set by hand would both be sent.
    api.client.cookies.clear()
    api.client.cookies.set(name, value)


def _sha256(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def _request_link(api: Api, email: str) -> str:
    response = api.client.post("/api/v1/auth/email-links", json={"email": email})
    assert response.status_code == 202, response.text
    return api.sender.last_token()


def _sign_in(api: Api, email: str, browser: TestClient | None = None) -> Response:
    client = browser or api.client
    response = client.post("/api/v1/auth/sessions", json={"token": _request_link(api, email)})
    assert response.status_code == 201, response.text
    return response


def _session_cookie_header(response: Response) -> str:
    headers = [h for h in response.headers.get_list("set-cookie") if h.startswith(SESSION_COOKIE)]
    assert len(headers) == 1
    return headers[0]


def _users(db: Session, email: str) -> list[AuthUser]:
    return list(db.scalars(select(AuthUser).where(AuthUser.email == email)))


def _count(db: Session, model: type[Base], *where: ColumnElement[bool]) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


# Email link


def test_an_email_link_signs_in_and_creates_the_user_and_account_once(
    api: Api, db: Session
) -> None:
    response = _sign_in(api, "Ana@Example.com")

    link = api.sender.sent[-1][1]
    assert link.startswith(f"{SETTINGS.frontend_url}/sign-in/email#token=")
    body = response.json()
    assert body["email"] == "ana@example.com"
    cookie = _session_cookie_header(response).lower()
    assert {"httponly", "secure", "samesite=lax"} <= {p.strip() for p in cookie.split(";")}

    current = api.client.get("/api/v1/auth/sessions/current")
    assert current.status_code == 200
    assert current.json() == body

    [user] = _users(db, "ana@example.com")
    assert user.email_verified_at is not None
    assert _count(db, Account, Account.auth_user_id == user.id) == 1

    # A second sign-in finds the same user and account.
    assert _sign_in(api, "ana@example.com").json()["account_id"] == body["account_id"]
    assert len(_users(db, "ana@example.com")) == 1


def test_the_database_stores_only_the_hash_of_link_and_session_tokens(
    api: Api, db: Session
) -> None:
    link_token = _request_link(api, "ana@example.com")
    response = api.client.post("/api/v1/auth/sessions", json={"token": link_token})
    session_token = api.client.cookies[SESSION_COOKIE]

    stored_link = db.scalars(select(EmailVerification.token_hash)).one()
    stored_session = db.scalars(select(AuthSession.token_hash)).one()
    assert response.status_code == 201
    assert stored_link == _sha256(link_token)
    assert stored_session == _sha256(session_token)
    assert link_token.encode() not in (stored_link, stored_session)
    assert session_token not in response.text


def test_a_link_works_only_once(api: Api, db: Session) -> None:
    token = _request_link(api, "ana@example.com")
    first = api.client.post("/api/v1/auth/sessions", json={"token": token})
    second = api.client.post("/api/v1/auth/sessions", json={"token": token})

    assert first.status_code == 201
    assert second.status_code == 400
    assert _count(db, AuthSession) == 1


def test_a_link_can_be_previewed_without_using_it_up(api: Api, db: Session) -> None:
    # The editor shows "Sign in as ana@example.com?" first, so a link someone sent for their own
    # account cannot sign the user in to it unnoticed.
    token = _request_link(api, "Ana@example.com")

    preview = api.client.post("/api/v1/auth/email-links/preview", json={"token": token})

    assert preview.status_code == 200
    assert preview.json() == {"email": "ana@example.com"}
    assert _users(db, "ana@example.com") == []
    assert SESSION_COOKIE not in preview.headers.get("set-cookie", "")
    assert api.client.post("/api/v1/auth/sessions", json={"token": token}).status_code == 201


@pytest.mark.parametrize("state", ["used", "expired", "other purpose", "unknown"])
def test_a_link_that_cannot_sign_in_cannot_be_previewed_either(
    api: Api, db: Session, state: str
) -> None:
    token = _request_link(api, "ana@example.com")
    if state == "used":
        api.client.post("/api/v1/auth/sessions", json={"token": token})
    elif state == "expired":
        db.execute(update(EmailVerification).values(expires_at=func.now() - timedelta(seconds=1)))
    elif state == "other purpose":
        db.execute(update(EmailVerification).values(purpose=VerificationPurpose.PASSWORD_RESET))
    else:
        token = new_token()

    preview = api.client.post("/api/v1/auth/email-links/preview", json={"token": token})

    assert preview.status_code == 400
    assert "ana@example.com" not in preview.text


def test_an_expired_link_is_refused_and_creates_nothing(api: Api, db: Session) -> None:
    token = _request_link(api, "ana@example.com")
    db.execute(update(EmailVerification).values(expires_at=func.now() - timedelta(seconds=1)))

    response = api.client.post("/api/v1/auth/sessions", json={"token": token})

    assert response.status_code == 400
    assert _users(db, "ana@example.com") == []
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")


def test_a_link_for_another_purpose_cannot_sign_in(api: Api, db: Session) -> None:
    token = new_token()
    db.execute(
        insert(EmailVerification).values(
            email="ana@example.com",
            purpose=VerificationPurpose.PASSWORD_RESET,
            token_hash=_sha256(token),
            expires_at=func.now() + timedelta(minutes=15),
        )
    )

    response = api.client.post("/api/v1/auth/sessions", json={"token": token})

    assert response.status_code == 400
    assert _count(db, AuthSession) == 0


@pytest.mark.parametrize(
    ("token", "status"), [(new_token(), 400), ("short", 422), ("x" * 43 + "/", 422)]
)
def test_unknown_or_malformed_tokens_are_refused(api: Api, token: str, status: int) -> None:
    assert api.client.post("/api/v1/auth/sessions", json={"token": token}).status_code == status


def test_the_answer_does_not_tell_whether_an_email_has_an_account(
    ana_account: Account, api: Api
) -> None:
    known = api.client.post("/api/v1/auth/email-links", json={"email": "ana@example.com"})
    unknown = api.client.post("/api/v1/auth/email-links", json={"email": "nadie@example.com"})

    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())


def test_too_many_links_for_one_email_are_refused_whatever_its_casing(
    api: Api, db: Session
) -> None:
    for _ in range(3):
        _request_link(api, "ana@example.com")

    again = api.client.post("/api/v1/auth/email-links", json={"email": "ANA@example.com"})
    other = api.client.post("/api/v1/auth/email-links", json={"email": "luis@example.com"})

    assert again.status_code == 429
    assert other.status_code == 202
    assert _count(db, EmailVerification, EmailVerification.email == "ana@example.com") == 3


@pytest.mark.parametrize("email", ["not-an-email", "ana@localhost", "a" * 250 + "@example.com"])
def test_invalid_emails_are_refused_before_anything_is_stored(
    api: Api, db: Session, email: str
) -> None:
    response = api.client.post("/api/v1/auth/email-links", json={"email": email})

    assert response.status_code == 422
    assert _count(db, EmailVerification) == 0


def test_outside_development_no_link_is_created_until_there_is_an_email_provider(
    api: Api, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    del app.dependency_overrides[email_sender]
    monkeypatch.setattr(SETTINGS, "app_env", "production")

    response = api.client.post("/api/v1/auth/email-links", json={"email": "ana@example.com"})

    assert response.status_code == 503
    assert _count(db, EmailVerification) == 0


def test_the_console_sender_never_logs_the_full_email(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        ConsoleEmailSender().send_sign_in_link("ana.lopez@example.com", "https://x/#token=t")

    assert "ana.lopez@example.com" not in caplog.text
    assert "a***@example.com" in caplog.text


# Account takeover through an email that was never proven


def test_proving_the_email_drops_a_password_set_before_it_was_verified(
    api: Api, db: Session
) -> None:
    # Someone signed up with Ana's email and a password, but never proved they own it.
    squatter = AuthUser(email="ana@example.com")
    db.add(squatter)
    db.flush()
    db.add(PasswordCredential(user_id=squatter.id, password_hash=ARGON2_HASH))
    db.flush()

    _sign_in(api, "ana@example.com")

    assert _count(db, PasswordCredential, PasswordCredential.user_id == squatter.id) == 0


def test_a_verified_users_password_is_kept(api: Api, db: Session) -> None:
    user = AuthUser(email="ana@example.com", email_verified_at=func.now())
    db.add(user)
    db.flush()
    db.add(PasswordCredential(user_id=user.id, password_hash=ARGON2_HASH))
    db.flush()

    _sign_in(api, "ana@example.com")

    assert _count(db, PasswordCredential, PasswordCredential.user_id == user.id) == 1


# Sessions


@pytest.mark.parametrize("cookie", [None, "", "garbage", new_token()])
def test_without_a_live_session_the_route_answers_401(api: Api, cookie: str | None) -> None:
    if cookie is not None:
        _use_cookie(api, SESSION_COOKIE, cookie)

    assert api.client.get("/api/v1/auth/sessions/current").status_code == 401


def test_an_expired_session_is_refused(api: Api, db: Session) -> None:
    _sign_in(api, "ana@example.com")
    db.execute(update(AuthSession).values(expires_at=func.now() - timedelta(seconds=1)))

    assert api.client.get("/api/v1/auth/sessions/current").status_code == 401


def test_sign_out_ends_the_session_even_for_a_copied_cookie(api: Api, db: Session) -> None:
    _sign_in(api, "ana@example.com")
    copied = api.client.cookies[SESSION_COOKIE]

    response = api.client.delete("/api/v1/auth/sessions/current")

    assert response.status_code == 204
    assert "max-age=0" in _session_cookie_header(response).lower()
    assert _count(db, AuthSession) == 0
    _use_cookie(api, SESSION_COOKIE, copied)
    assert api.client.get("/api/v1/auth/sessions/current").status_code == 401
    # Signing out again is harmless.
    assert api.client.delete("/api/v1/auth/sessions/current").status_code == 204


def _current(client: TestClient) -> Response:
    return client.get("/api/v1/auth/sessions/current")


def _last_used(db: Session, ago: timedelta) -> None:
    db.execute(update(AuthSession).values(last_used_at=func.now() - ago))


def test_a_session_used_within_the_hour_is_neither_renewed_nor_rotated(
    api: Api, db: Session
) -> None:
    _sign_in(api, "ana@example.com")
    token = api.client.cookies[SESSION_COOKIE]
    db.execute(update(AuthSession).values(expires_at=func.now() + timedelta(days=1)))

    response = _current(api.client)

    assert response.status_code == 200
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")
    assert db.scalar(select(AuthSession.expires_at - func.now())) == timedelta(days=1)
    assert db.scalar(select(AuthSession.token_hash)) == _sha256(token)


def test_a_session_idle_for_an_hour_is_renewed_with_a_new_token(api: Api, db: Session) -> None:
    _sign_in(api, "ana@example.com")
    old = api.client.cookies[SESSION_COOKIE]
    db.execute(update(AuthSession).values(expires_at=func.now() + timedelta(days=1)))
    _last_used(db, timedelta(hours=2))

    response = _current(api.client)

    new = api.client.cookies[SESSION_COOKIE]
    assert response.status_code == 200
    assert new != old
    assert "max-age=2592000" in _session_cookie_header(response).lower()
    session = db.scalars(select(AuthSession)).one()
    db.refresh(session)
    assert (session.token_hash, session.previous_token_hash) == (_sha256(new), _sha256(old))
    assert db.scalar(select(AuthSession.expires_at - func.now())) == timedelta(days=30)
    assert _current(api.client).status_code == 200


def test_the_replaced_token_still_works_during_the_grace_period(api: Api, db: Session) -> None:
    # A request that left with the old cookie just before the rotation.
    _sign_in(api, "ana@example.com")
    old = api.client.cookies[SESSION_COOKIE]
    _last_used(db, timedelta(hours=2))
    _current(api.client)
    db.execute(update(AuthSession).values(rotated_at=func.now() - timedelta(minutes=1)))

    in_flight = _browser()
    in_flight.cookies.set(SESSION_COOKIE, old)
    response = _current(in_flight)

    assert response.status_code == 200
    # It does not rotate again nor hand out a token: the browser already has the new one.
    assert SESSION_COOKIE not in response.headers.get("set-cookie", "")
    assert _count(db, AuthSession) == 1


def test_a_replaced_token_used_after_the_grace_period_ends_the_session(
    api: Api, db: Session
) -> None:
    # Someone copied Ana's cookie. Ana keeps working and her browser gets a new token; when the
    # copy is used later, the session ends for both: the copy is useless and Ana signs in again.
    _sign_in(api, "ana@example.com")
    thief = _browser()
    thief.cookies.set(SESSION_COOKIE, api.client.cookies[SESSION_COOKIE])
    _last_used(db, timedelta(hours=2))
    assert _current(api.client).status_code == 200
    db.execute(update(AuthSession).values(rotated_at=func.now() - timedelta(minutes=3)))

    assert _current(thief).status_code == 401
    assert _count(db, AuthSession) == 0
    assert _current(api.client).status_code == 401


def test_a_thief_who_rotates_first_is_also_cut_off(api: Api, db: Session) -> None:
    _sign_in(api, "ana@example.com")
    thief = _browser()
    thief.cookies.set(SESSION_COOKIE, api.client.cookies[SESSION_COOKIE])
    _last_used(db, timedelta(hours=2))
    assert _current(thief).status_code == 200  # the thief gets the new token
    db.execute(update(AuthSession).values(rotated_at=func.now() - timedelta(minutes=3)))

    assert _current(api.client).status_code == 401  # Ana's old token: reuse detected
    assert _current(thief).status_code == 401
    assert _count(db, AuthSession) == 0


def test_signing_in_again_ends_the_previous_session_of_this_browser(api: Api, db: Session) -> None:
    _sign_in(api, "ana@example.com")
    copied = api.client.cookies[SESSION_COOKIE]

    _sign_in(api, "ana@example.com")

    assert _count(db, AuthSession) == 1
    stale = _browser()
    stale.cookies.set(SESSION_COOKIE, copied)
    assert _current(stale).status_code == 401
    assert _current(api.client).status_code == 200


def test_signing_in_with_google_also_ends_the_previous_session(api: Api, db: Session) -> None:
    _sign_in(api, "ana@example.com")
    copied = api.client.cookies[SESSION_COOKIE]

    assert _signed_in_with_google(_google_round_trip(api, _profile()))

    stale = _browser()
    stale.cookies.set(SESSION_COOKIE, copied)
    assert _current(stale).status_code == 401
    assert _count(db, AuthSession) == 1


def _app_with_routes_that_fail(db: Session) -> FastAPI:
    """A small app shaped like the real one, with routes that need a session and then fail."""
    other = FastAPI()
    other.add_middleware(SessionCookieMiddleware)
    other.dependency_overrides[get_db] = lambda: db

    @other.get("/not-found")
    def not_found(_: Annotated[CurrentUser, Depends(get_current_user)]) -> None:
        raise HTTPException(404)

    @other.get("/crash")
    def crash(_: Annotated[CurrentUser, Depends(get_current_user)]) -> None:
        raise RuntimeError("unexpected")

    @other.get("/own-response")
    def own_response(_: Annotated[CurrentUser, Depends(get_current_user)]) -> PlainTextResponse:
        return PlainTextResponse("file")

    return other


@pytest.mark.parametrize(
    ("path", "status"), [("/not-found", 404), ("/own-response", 200), ("/crash", 500)]
)
def test_a_rotated_token_reaches_the_browser_even_if_the_route_then_fails(
    api: Api, db: Session, path: str, status: int
) -> None:
    # Without it, the database has the new token, the browser keeps the old one, and the user is
    # signed out two minutes later as if the cookie had been stolen.
    _sign_in(api, "ana@example.com")
    old = api.client.cookies[SESSION_COOKIE]
    _last_used(db, timedelta(hours=2))
    browser = TestClient(
        _app_with_routes_that_fail(db),
        base_url="https://testserver",
        raise_server_exceptions=False,
    )
    browser.cookies.set(SESSION_COOKIE, old)

    response = browser.get(path)

    assert response.status_code == status
    new = _session_cookie_header(response).split(";")[0].removeprefix(f"{SESSION_COOKIE}=")
    assert new != old
    assert db.scalar(select(AuthSession.token_hash)) == _sha256(new)


def test_sign_out_everywhere_is_not_undone_by_a_rotation_in_the_same_request(
    api: Api, db: Session
) -> None:
    _sign_in(api, "ana@example.com")
    _last_used(db, timedelta(hours=2))  # this request rotates, then ends every session

    response = api.client.delete("/api/v1/auth/sessions")

    assert "max-age=0" in _session_cookie_header(response).lower()
    assert SESSION_COOKIE not in api.client.cookies


def test_two_browsers_each_get_their_own_session(api: Api) -> None:
    other = _browser()
    ana = _sign_in(api, "ana@example.com")
    luis = _sign_in(api, "luis@example.com", other)

    assert _current(api.client).json() == ana.json()
    assert _current(other).json() == luis.json()


def test_sign_out_everywhere_ends_every_session_of_the_user_only(api: Api, db: Session) -> None:
    phone, luis = _browser(), _browser()
    _sign_in(api, "ana@example.com")
    _sign_in(api, "ana@example.com", phone)
    _sign_in(api, "luis@example.com", luis)

    response = api.client.delete("/api/v1/auth/sessions")

    assert response.status_code == 204
    assert "max-age=0" in _session_cookie_header(response).lower()
    assert (_current(api.client).status_code, _current(phone).status_code) == (401, 401)
    assert _current(luis).status_code == 200
    assert _count(db, AuthSession) == 1


def test_sign_out_everywhere_needs_a_session(api: Api) -> None:
    assert api.client.delete("/api/v1/auth/sessions").status_code == 401


def test_signing_out_with_the_replaced_token_still_ends_the_session(api: Api, db: Session) -> None:
    _sign_in(api, "ana@example.com")
    old = api.client.cookies[SESSION_COOKIE]
    _last_used(db, timedelta(hours=2))
    _current(api.client)

    in_flight = _browser()
    in_flight.cookies.set(SESSION_COOKIE, old)
    assert in_flight.delete("/api/v1/auth/sessions/current").status_code == 204
    assert _count(db, AuthSession) == 0


def test_a_session_acts_only_for_its_own_account(
    luis_account: Account, api: Api, db: Session
) -> None:
    luis_account_id = luis_account.id
    ana_account_id = uuid.UUID(_sign_in(api, "ana@example.com").json()["account_id"])

    current = api.client.get("/api/v1/auth/sessions/current")

    assert current.json()["account_id"] == str(ana_account_id)
    # The request left the database session acting for Ana: RLS hides Luis's account.
    visible = set(db.scalars(select(Account.id)))
    assert visible == {ana_account_id}
    assert luis_account_id not in visible


# The agent validates the same cookie with auth.find_session()


def _find_as_agent(db: Session, token: str) -> uuid.UUID | None:
    db.execute(text("RESET ROLE"))
    as_role(db, AGENT_ROLE)
    return db.scalar(
        text("SELECT user_id FROM auth.find_session(:token_hash)"),
        {"token_hash": _sha256(token)},
    )


def test_the_agent_recognises_a_platform_session(api: Api, db: Session) -> None:
    user_id = _sign_in(api, "ana@example.com").json()["user_id"]

    assert str(_find_as_agent(db, api.client.cookies[SESSION_COOKIE])) == user_id


@pytest.mark.parametrize(
    ("rotated_ago", "found"), [(timedelta(minutes=1), True), (timedelta(minutes=3), False)]
)
def test_the_agent_applies_the_same_grace_period(
    api: Api, db: Session, rotated_ago: timedelta, found: bool
) -> None:
    _sign_in(api, "ana@example.com")
    old = api.client.cookies[SESSION_COOKIE]
    _last_used(db, timedelta(hours=2))
    _current(api.client)
    db.execute(update(AuthSession).values(rotated_at=func.now() - rotated_ago))

    assert (_find_as_agent(db, old) is not None) is found
    assert _find_as_agent(db, api.client.cookies[SESSION_COOKIE]) is not None


def test_the_agent_does_not_see_an_expired_session(api: Api, db: Session) -> None:
    _sign_in(api, "ana@example.com")
    db.execute(update(AuthSession).values(expires_at=func.now() - timedelta(seconds=1)))

    assert _find_as_agent(db, api.client.cookies[SESSION_COOKIE]) is None


def test_only_the_platform_and_the_agent_may_look_up_sessions(db: Session) -> None:
    def can_execute(role: str) -> bool:
        return bool(
            db.scalar(
                select(func.has_function_privilege(role, "auth.find_session(bytea)", "EXECUTE"))
            )
        )

    assert can_execute(PLATFORM_ROLE) and can_execute(AGENT_ROLE)
    assert not can_execute("public")
    config = db.scalar(
        text("SELECT proconfig FROM pg_proc WHERE oid = 'auth.find_session(bytea)'::regprocedure")
    )
    assert config == ["search_path=pg_catalog, pg_temp"]


# Requests from other sites


@pytest.mark.parametrize("origin", [None, "https://evil.example", "null"])
def test_requests_that_change_data_need_one_of_our_origins(
    api: Api, db: Session, origin: str | None
) -> None:
    _sign_in(api, "ana@example.com")
    headers = {"Origin": origin} if origin else {}
    if origin is None:
        del api.client.headers["Origin"]

    link = api.client.post(
        "/api/v1/auth/email-links", json={"email": "luis@example.com"}, headers=headers
    )
    sign_out = api.client.delete("/api/v1/auth/sessions/current", headers=headers)

    assert (link.status_code, sign_out.status_code) == (403, 403)
    assert _count(db, EmailVerification, EmailVerification.email == "luis@example.com") == 0
    assert _count(db, AuthSession) == 1


def test_swagger_on_the_api_origin_may_send_requests(api: Api) -> None:
    response = api.client.post(
        "/api/v1/auth/email-links",
        json={"email": "ana@example.com"},
        headers={"Origin": SETTINGS.api_url},
    )
    assert response.status_code == 202


@pytest.mark.parametrize(
    ("origin", "allowed"), [(SETTINGS.frontend_url, True), ("https://evil.example", False)]
)
def test_only_the_editor_may_send_cross_origin_requests_with_the_cookie(
    api: Api, origin: str, allowed: bool
) -> None:
    preflight = api.client.options(
        "/api/v1/auth/sessions/current",
        headers={"Origin": origin, "Access-Control-Request-Method": "DELETE"},
    )

    assert (preflight.headers.get("access-control-allow-origin") == origin) is allowed
    if allowed:
        assert preflight.headers["access-control-allow-credentials"] == "true"


# Google


def _profile(
    sub: str = "google-1", email: str = "ana@example.com", **extra: object
) -> GoogleProfile:
    values: dict[str, object] = {"sub": sub, "email": email, "email_verified": True, "name": "Ana"}
    return GoogleProfile.model_validate(values | extra)


def _google_round_trip(api: Api, profile: GoogleProfile | None) -> Response:
    api.google.profile = profile
    start = api.client.get("/api/v1/auth/google")
    assert start.status_code == 302
    return api.client.get("/api/v1/auth/google/callback", params={"code": "c", "state": "state-1"})


def _signed_in_with_google(response: Response) -> bool:
    return response.headers["location"] == SETTINGS.frontend_url and any(
        h.startswith(f"{SESSION_COOKIE}=") for h in response.headers.get_list("set-cookie")
    )


def _failed_with_google(response: Response) -> bool:
    return response.status_code == 302 and response.headers["location"] == (
        f"{SETTINGS.frontend_url}/sign-in?error=google"
    )


def test_google_start_uses_pkce_and_keeps_the_state_in_this_browser(api: Api) -> None:
    redirect_uri = f"{SETTINGS.api_url}/api/v1/auth/google/callback"
    real = AuthlibGoogleClient("client-id", "secret", redirect_uri)
    app.dependency_overrides[google_client] = lambda: real

    response = api.client.get("/api/v1/auth/google")

    query = parse_qs(urlparse(response.headers["location"]).query)
    assert response.status_code == 302
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == [redirect_uri]
    state, _, verifier = api.client.cookies[GOOGLE_COOKIE].partition(".")
    assert query["state"] == [state]
    assert verifier not in response.headers["location"]
    google_cookie = [
        h for h in response.headers.get_list("set-cookie") if h.startswith(GOOGLE_COOKIE)
    ][0].lower()
    assert "httponly" in google_cookie and "secure" in google_cookie


def test_the_google_callback_route_is_where_google_is_told_to_return(api: Api) -> None:
    paths = api.client.get("/api/v1/openapi.json").json()["paths"]
    assert "/api/v1/auth/google/callback" in paths


def test_google_creates_the_user_account_and_session_the_first_time(api: Api, db: Session) -> None:
    response = _google_round_trip(api, _profile())

    assert _signed_in_with_google(response)
    assert api.google.calls == [("c", "v" * 64)]
    [user] = _users(db, "ana@example.com")
    assert user.name == "Ana" and user.email_verified_at is not None
    assert _count(db, LinkedAccount, LinkedAccount.user_id == user.id) == 1
    assert _count(db, Account, Account.auth_user_id == user.id) == 1
    assert GOOGLE_COOKIE not in api.client.cookies


@pytest.mark.parametrize(
    ("cookie", "params"),
    [
        (None, {"code": "c", "state": "state-1"}),  # did not start here
        ("other-state." + "v" * 64, {"code": "c", "state": "state-1"}),  # someone else's state
        ("state-1." + "v" * 64, {"code": "c"}),  # no state
        ("state-1." + "v" * 64, {"state": "state-1"}),  # no code
        ("state-1." + "v" * 64, {"code": "c", "state": "estado-ñ"}),  # non-ASCII state
    ],
)
def test_a_google_callback_this_browser_did_not_start_is_refused(
    api: Api, db: Session, cookie: str | None, params: dict[str, str]
) -> None:
    api.google.profile = _profile()
    if cookie is not None:
        _use_cookie(api, GOOGLE_COOKIE, cookie)

    response = api.client.get("/api/v1/auth/google/callback", params=params)

    assert _failed_with_google(response)
    assert api.google.calls == []
    assert _count(db, AuthSession) == 0


def test_an_unverified_google_email_cannot_take_over_an_existing_user(
    ana_account: Account, api: Api, db: Session
) -> None:
    response = _google_round_trip(api, _profile(email_verified=False))

    assert _failed_with_google(response)
    assert _count(db, LinkedAccount) == 0
    assert _count(db, AuthSession) == 0


def test_a_verified_google_email_joins_the_existing_user(
    ana_account: Account, api: Api, db: Session
) -> None:
    assert _signed_in_with_google(_google_round_trip(api, _profile()))

    [user] = _users(db, "ana@example.com")
    assert user.id == ana_account.auth_user_id
    assert _count(db, Account) == 1


def test_a_linked_google_account_signs_in_even_after_its_email_changes(
    api: Api, db: Session
) -> None:
    assert _signed_in_with_google(_google_round_trip(api, _profile()))
    [ana] = _users(db, "ana@example.com")

    response = _google_round_trip(api, _profile(email="ana.nueva@example.com"))

    assert _signed_in_with_google(response)
    assert api.client.get("/api/v1/auth/sessions/current").json()["user_id"] == str(ana.id)
    assert _users(db, "ana.nueva@example.com") == []


def test_a_user_cannot_be_linked_to_a_second_google_account(api: Api, db: Session) -> None:
    assert _signed_in_with_google(_google_round_trip(api, _profile(sub="google-1")))

    response = _google_round_trip(api, _profile(sub="google-2"))

    assert _failed_with_google(response)
    assert _count(db, LinkedAccount) == 1


def test_a_failure_at_google_sends_the_user_back_with_an_error(api: Api, db: Session) -> None:
    assert _failed_with_google(_google_round_trip(api, None))
    assert _count(db, AuthUser) == 0


def test_google_answers_503_when_it_is_not_configured(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    del app.dependency_overrides[google_client]
    monkeypatch.setattr(SETTINGS, "google_client_id", None)

    assert api.client.get("/api/v1/auth/google").status_code == 503


# Settings


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"google_client_id": None}, "GOOGLE_CLIENT_ID"),
        # `.env.example` leaves it as `GOOGLE_CLIENT_SECRET=`: empty must not count as set.
        ({"google_client_secret": ""}, "GOOGLE_CLIENT_SECRET"),
        ({"frontend_url": "http://editor.example"}, "FRONTEND_URL must use https"),
        ({"api_url": "http://api.example"}, "API_URL must use https"),
    ],
)
def test_outside_development_google_and_https_are_required(
    overrides: dict[str, object], error: str
) -> None:
    valid: dict[str, object] = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://app@db/app",
        "frontend_url": "https://editor.example",
        "api_url": "https://api.example",
        "google_client_id": "id",
        "google_client_secret": "secret",
    }
    Settings(_env_file=None, **valid)  # type: ignore[arg-type]  # values typed as object
    with pytest.raises(ValueError, match=error):
        Settings(_env_file=None, **(valid | overrides))  # type: ignore[arg-type]  # same


# Concurrency: real commits, so each test cleans up its own rows.


def _run_together(*calls: Callable[[], None]) -> None:
    barrier = threading.Barrier(len(calls))

    def run(call: Callable[[], None]) -> None:
        barrier.wait()
        call()

    threads = [threading.Thread(target=run, args=(call,)) for call in calls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


@pytest.fixture
def committed_email() -> Iterator[str]:
    email = f"{uuid.uuid4().hex}@example.com"
    yield email
    with SessionLocal() as db:
        user_ids = select(AuthUser.id).where(AuthUser.email == email).scalar_subquery()
        db.execute(delete(Account).where(Account.auth_user_id.in_(user_ids)))
        db.execute(delete(AuthUser).where(AuthUser.email == email))
        db.execute(delete(EmailVerification).where(EmailVerification.email == email))
        db.commit()


def _link_token(email: str) -> str:
    sender = FakeSender()
    with SessionLocal() as db:
        request_sign_in_link(db, email, sender)
    return sender.last_token()


def test_the_same_link_used_twice_at_once_starts_one_session(committed_email: str) -> None:
    token = _link_token(committed_email)
    outcomes: list[str] = []

    def use_link() -> None:
        with SessionLocal() as db:
            try:
                sign_in_with_email_link(db, token, None)
                outcomes.append("signed in")
            except InvalidEmailLink:
                outcomes.append("refused")

    _run_together(use_link, use_link)

    assert sorted(outcomes) == ["refused", "signed in"]


def test_two_first_sign_ins_of_a_new_user_at_once_create_one_user_and_account(
    committed_email: str,
) -> None:
    tokens = [_link_token(committed_email), _link_token(committed_email)]
    account_ids: list[uuid.UUID] = []

    def sign_in(token: str) -> Callable[[], None]:
        def call() -> None:
            with SessionLocal() as db:
                account_ids.append(sign_in_with_email_link(db, token, None).account_id)

        return call

    _run_together(*(sign_in(token) for token in tokens))

    assert len(account_ids) == 2 and account_ids[0] == account_ids[1]
    with SessionLocal() as db:
        assert len(_users(db, committed_email)) == 1


def test_two_requests_at_once_rotate_the_token_only_once(committed_email: str) -> None:
    with SessionLocal() as db:
        token = sign_in_with_email_link(db, _link_token(committed_email), None).session_token
        db.execute(
            update(AuthSession)
            .where(AuthSession.token_hash == _sha256(token))
            .values(last_used_at=func.now() - timedelta(hours=2))
        )
        db.commit()
    new_tokens: list[str | None] = []

    def request() -> None:
        with SessionLocal() as db:
            found = find_session(db, token)
            assert found is not None
            new_tokens.append(found.new_token)

    _run_together(request, request)

    rotated = [t for t in new_tokens if t is not None]
    assert len(new_tokens) == 2 and len(rotated) == 1
    with SessionLocal() as db:
        assert find_session(db, rotated[0]) is not None
