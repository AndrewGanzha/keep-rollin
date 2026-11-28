import asyncio
import smtplib
import ssl
from contextlib import suppress
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate
from math import isfinite
from typing import Literal
from uuid import UUID

from src.infrastructure.email.renderer import RenderedEmail


class SmtpDeliveryError(RuntimeError):
    """SMTP failed before confirming receipt of the message."""


class SmtpEmailSender:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_address: str,
        timeout_seconds: float,
        security: Literal["plain", "starttls", "tls"],
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        if not isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("invalid_smtp_timeout")
        if security not in ("plain", "starttls", "tls"):
            raise ValueError("invalid_smtp_security")
        if (username is None) != (password is None):
            raise ValueError("incomplete_smtp_credentials")
        if username is not None and security == "plain":
            raise ValueError("smtp_authentication_requires_tls")
        self._host = host
        self._port = port
        self._from_address = _mailbox(from_address)
        self._timeout_seconds = timeout_seconds
        self._security = security
        self._username = username
        self._password = password
        self._tls_context = ssl.create_default_context() if security != "plain" else None

    async def send(self, *, recipient: str, email: RenderedEmail, message_id: UUID) -> None:
        to_address = _mailbox(recipient)
        message = EmailMessage()
        message["From"] = self._from_address
        message["To"] = to_address
        message["Date"] = formatdate()
        message["Message-ID"] = f"<{message_id}@{self._from_address.domain}>"
        message["Subject"] = email.subject
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")

        try:
            await asyncio.to_thread(self._send_message, message)
        except OSError:
            # The server response can contain private addresses or message content.
            raise SmtpDeliveryError("smtp_delivery_failed") from None

    def _send_message(self, message: EmailMessage) -> None:
        connection: smtplib.SMTP
        if self._security == "tls":
            connection = smtplib.SMTP_SSL(
                self._host, self._port, timeout=self._timeout_seconds, context=self._tls_context
            )
        else:
            connection = smtplib.SMTP(self._host, self._port, timeout=self._timeout_seconds)

        try:
            if self._security == "starttls":
                connection.starttls(context=self._tls_context)
            if self._username is not None and self._password is not None:
                connection.login(self._username, self._password)
            connection.send_message(message)
            # DATA has been accepted. A QUIT failure must not cause a duplicate delivery.
            with suppress(OSError):
                connection.quit()
        finally:
            with suppress(OSError):
                connection.close()


def _mailbox(value: str) -> Address:
    try:
        address = Address(addr_spec=value)
    except (HeaderParseError, ValueError):
        raise ValueError("invalid_email_address") from None
    if not address.domain or address.addr_spec != value:
        raise ValueError("invalid_email_address")
    return address
