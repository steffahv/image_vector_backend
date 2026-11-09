import uuid

from pydantic import BaseModel

from app.auth.schemas.email_link import EmailLinkToken


class SessionCreate(EmailLinkToken):
    """Sign in with the token of an email link."""


class CurrentUserResponse(BaseModel):
    user_id: uuid.UUID
    account_id: uuid.UUID
    email: str
    name: str | None
    image_url: str | None
