"""The OAuth round trip with Google, through Authlib (VEC-40).

Authorization code flow with PKCE and `state`. The profile comes from Google's userinfo endpoint,
called with the access token just received over TLS, so there is no ID token to verify by hand.
No Google token is stored: Google is only used to sign in.
"""

from dataclasses import dataclass
from typing import Protocol

import httpx2
from authlib.common.security import generate_token
from authlib.integrations.base_client import OAuthError
from authlib.integrations.httpx_client import OAuth2Client
from pydantic import BaseModel, EmailStr, Field

from app.auth.service.errors import GoogleSignInFailed, GoogleSignInUnavailable
from app.core.config import get_settings

GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPE = "openid email profile"
GOOGLE_TIMEOUT_SECONDS = 10
# PKCE allows 43 to 128 characters; generate_token uses letters and digits only.
CODE_VERIFIER_LENGTH = 64
# Path of the callback route, after the API URL.
GOOGLE_CALLBACK_PATH = "/api/v1/auth/google/callback"


class GoogleProfile(BaseModel):
    """What sign-in uses from Google's userinfo response, with limits on every field."""

    subject: str = Field(alias="sub", min_length=1, max_length=255)
    email: EmailStr = Field(max_length=254)
    email_verified: bool = False
    name: str | None = Field(default=None, max_length=200)
    picture: str | None = Field(default=None, max_length=2048)


@dataclass(frozen=True)
class GoogleAuthorization:
    """Where to send the user, plus the values the callback must get back."""

    url: str
    state: str
    code_verifier: str


class GoogleClient(Protocol):
    def start(self) -> GoogleAuthorization: ...

    def fetch_profile(self, code: str, code_verifier: str) -> GoogleProfile: ...


class AuthlibGoogleClient:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    def _client(self) -> OAuth2Client:
        return OAuth2Client(
            self._client_id,
            self._client_secret,
            scope=GOOGLE_SCOPE,
            redirect_uri=self._redirect_uri,
            code_challenge_method="S256",
            timeout=GOOGLE_TIMEOUT_SECONDS,
        )

    def start(self) -> GoogleAuthorization:
        code_verifier = generate_token(CODE_VERIFIER_LENGTH)
        with self._client() as client:
            url, state = client.create_authorization_url(
                GOOGLE_AUTHORIZE_URL, code_verifier=code_verifier
            )
        return GoogleAuthorization(url=url, state=state, code_verifier=code_verifier)

    def fetch_profile(self, code: str, code_verifier: str) -> GoogleProfile:
        try:
            with self._client() as client:
                client.fetch_token(GOOGLE_TOKEN_URL, code=code, code_verifier=code_verifier)
                response = client.get(GOOGLE_USERINFO_URL)
                response.raise_for_status()
                return GoogleProfile.model_validate(response.json())
        # ValueError also covers a body that is not JSON and a profile that fails validation.
        except (OAuthError, httpx2.HTTPError, ValueError) as error:
            raise GoogleSignInFailed from error


def get_google_client() -> GoogleClient:
    settings = get_settings()
    if not settings.google_client_id or settings.google_client_secret is None:
        raise GoogleSignInUnavailable
    return AuthlibGoogleClient(
        settings.google_client_id,
        settings.google_client_secret.get_secret_value(),
        f"{settings.api_url}{GOOGLE_CALLBACK_PATH}",
    )
