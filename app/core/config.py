"""Application settings.

What goes here:
- Every value read from the environment or `.env` (database URL, S3, OAuth keys, ...).
- One typed field per variable. Add the variable to `.env.example` at the same time.

Rules:
- No default values for secrets: the app must fail at startup if one is missing.
- Read settings through `get_settings()`, never with `os.getenv` elsewhere.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    """Settings read from the environment or .env, with no default credentials."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Environment = "development"
    database_url: str

    @property
    def api_docs_enabled(self) -> bool:
        """Swagger and ReDoc are public in development and staging, hidden in production."""
        return self.app_env != "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
