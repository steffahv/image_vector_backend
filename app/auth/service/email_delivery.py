"""Sending sign-in links by email.

The email provider is not chosen yet (VEC-40). Until then, development prints the link to the
console and every other environment refuses to send, so a link is never lost silently.
"""

import logging
from typing import Protocol

from app.auth.service.errors import EmailDeliveryUnavailable
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmailSender(Protocol):
    def send_sign_in_link(self, email: str, link: str) -> None: ...


def mask_email(email: str) -> str:
    """`ana@example.com` -> `a***@example.com`: enough to tell links apart in a log."""
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


class ConsoleEmailSender:
    """Development only: the link carries a live token, so it must never reach real logs."""

    def send_sign_in_link(self, email: str, link: str) -> None:
        logger.warning("Sign-in link for %s (development only): %s", mask_email(email), link)


def get_email_sender() -> EmailSender:
    if get_settings().app_env != "development":
        raise EmailDeliveryUnavailable
    return ConsoleEmailSender()
