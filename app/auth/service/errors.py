"""Auth errors. The router turns each one into an HTTP response.

Messages are generic on purpose: they never tell whether an email exists, nor why a link or a
Google sign-in failed in detail.
"""


class AuthError(Exception):
    """Base class for every auth error."""


class InvalidEmailLink(AuthError):
    """The link is unknown, already used, expired or for another purpose."""


class TooManyEmailLinks(AuthError):
    """Too many sign-in links were requested for this email recently."""


class EmailDeliveryUnavailable(AuthError):
    """No email provider is configured for this environment yet."""


class GoogleSignInUnavailable(AuthError):
    """Google sign-in is not configured for this environment."""


class GoogleSignInFailed(AuthError):
    """Google did not confirm the identity, or it cannot be linked to a user."""
