"""Application settings.

What goes here:
- Every value read from the environment or `.env` (database URL, S3, OAuth keys, ...).
- One typed field per variable. Add the variable to `.env.example` at the same time.

Rules:
- No default values for secrets: the app must fail at startup if one is missing.
- Read settings through `get_settings()`, never with `os.getenv` elsewhere.
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    """Settings read from the environment or .env, with no default credentials."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Environment = "development"
    database_url: str

    # Where the editor (Vue) and this API are served. They decide which origins may send
    # requests that change data, where email links point and where Google sends the user back.
    # The defaults are the local development servers.
    frontend_url: str = "http://localhost:5173"
    api_url: str = "http://localhost:8000"

    # Google sign-in. Optional only in development: without them the Google routes answer 503.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None

    # Domain of the session cookie. Unset: only the API's own host receives it. Set it to the
    # parent domain (e.g. `vectoredit.com`) when the agent runs on a sibling subdomain.
    session_cookie_domain: str | None = None

    @field_validator(
        "google_client_id", "google_client_secret", "session_cookie_domain", mode="before"
    )
    @classmethod
    def _empty_is_unset(cls, value: object) -> object:
        # `.env.example` leaves them as `NAME=`; an empty cookie domain would break the cookie.
        return None if value == "" else value

    @field_validator("frontend_url", "api_url")
    @classmethod
    def _without_trailing_slash(cls, url: str) -> str:
        # Compared as is with the Origin header, which never ends with a slash.
        return url.rstrip("/")

    @model_validator(mode="after")
    def _check_outside_development(self) -> Self:
        if self.app_env == "development":
            return self
        if not self.google_client_id or self.google_client_secret is None:
            raise ValueError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required")
        for name in ("frontend_url", "api_url"):
            if not getattr(self, name).startswith("https://"):
                raise ValueError(f"{name.upper()} must use https outside development")
        return self

    @property
    def api_docs_enabled(self) -> bool:
        """Swagger and ReDoc are public in development and staging, hidden in production."""
        return self.app_env != "production"

    @property
    def allowed_origins(self) -> frozenset[str]:
        """Origins that may send requests that change data: the editor and Swagger on the API."""
        return frozenset({self.frontend_url, self.api_url})


@lru_cache
def get_settings() -> Settings:
    return Settings()
