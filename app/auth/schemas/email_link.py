from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field

from app.auth.service import TOKEN_PATTERN

# Stored lowercased (CHECK email_lowercase), so Ana@Example.com and ana@example.com are one user.
NormalizedEmail = Annotated[EmailStr, Field(max_length=254), AfterValidator(str.lower)]


class EmailLinkCreate(BaseModel):
    email: NormalizedEmail


class EmailLinkResponse(BaseModel):
    detail: str = Field(
        examples=["If the address can receive email, a sign-in link is on its way."]
    )


class EmailLinkToken(BaseModel):
    """The token from a sign-in email link (the `#token=` part of the link)."""

    token: str = Field(pattern=TOKEN_PATTERN)


class EmailLinkPreviewResponse(BaseModel):
    """Who the link signs in as, for the editor to confirm before using it."""

    email: str
