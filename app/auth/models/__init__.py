"""SQLAlchemy tables for auth, in the `auth` PostgreSQL schema (VEC-29).

One file per table:
- user.py: `users` (AuthUser), one row per person, identified by email.
- linked_account.py: `accounts` (LinkedAccount), external identity providers (Google).
- session.py: `sessions` (AuthSession). Only the hash of the session token is stored.
- email_verification.py: `verifications` (EmailVerification), one-time email links
  (sign in, verify email, reset password).
- password_credential.py: `password_credentials` (PasswordCredential), optional password
  (Argon2id hash only).

Users sign in with an email link, email and password, or Google.
Sessions, email links, passwords and users are our own code; Authlib only handles the
Google OAuth round trip.
The product account lives in `platform.accounts` (app/documents/models/), not here.

Import every table here: Alembic and other modules import from `app.auth.models`.
"""

from app.auth.models.email_verification import EmailVerification, VerificationPurpose
from app.auth.models.linked_account import IdentityProvider, LinkedAccount
from app.auth.models.password_credential import PasswordCredential
from app.auth.models.session import AuthSession
from app.auth.models.user import AuthUser

__all__ = [
    "AuthSession",
    "AuthUser",
    "EmailVerification",
    "IdentityProvider",
    "LinkedAccount",
    "PasswordCredential",
    "VerificationPurpose",
]
