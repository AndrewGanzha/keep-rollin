import re
import smtplib
import ssl
from email.message import EmailMessage
from typing import Literal
from unittest.mock import Mock, call
from uuid import uuid4

import pytest

from src.infrastructure.email import (
    EMAIL_EVENT_TYPES,
    NotificationEmailRenderer,
    RenderedEmail,
    SmtpEmailSender,
)
from src.infrastructure.email.smtp import SmtpDeliveryError

TENANT_ORIGIN = "https://rental.example.test"
SENDER = "notifications@example.test"
RECIPIENT = "recipient@example.test"


def test_every_notification_has_distinct_russian_copy_and_tenant_link() -> None:
    paths = {
        "verification.approved": "/account/verification",
        "verification.rejected": "/account/verification",
        "booking.confirmed": "/account/rentals",
        "rental.closed": "/account/rentals",
        "booking.cancelled": "/account/rentals",
        "rental.ending_soon": "/account/rentals",
        "rental.overdue.user": "/account/rentals",
        "rental.overdue.admin": "/admin/rentals",
        "ticket.created.admin": "/admin/tickets",
        "ticket.updated.user": "/account/tickets",
        "ticket.resolved.user": "/account/tickets",
    }
    renderer = NotificationEmailRenderer()
    assert paths.keys() == EMAIL_EVENT_TYPES

    subjects: set[str] = set()
    bodies: set[str] = set()
    for event_type, path in paths.items():
        email = renderer.render(event_type, tenant_origin=TENANT_ORIGIN)
        link = f"{TENANT_ORIGIN}{path}"
        body = email.text.splitlines()[0]
        assert re.search(r"[\u0400-\u04ff]", email.subject)
        assert re.search(r"[\u0400-\u04ff]", body)
        assert body in email.html
        assert email.text.splitlines()[-1] == link
        assert f'href="{link}"' in email.html
        subjects.add(email.subject)
        bodies.add(body)

    assert len(subjects) == len(bodies) == len(paths)


@pytest.mark.parametrize(
    "origin",
    [
        "http://rental.example.test",
        "https://rental.example.test@other.example.test",
        "https://rental.example.test/",
        "https://rental.example.test?next=https://other.example.test",
        "https://rental.example.test\\other",
        "https://rental.example.test\n",
        "https://rental..example.test",
    ],
)
def test_email_renderer_requires_canonical_https_origin(origin: str) -> None:
    with pytest.raises(ValueError, match=r"^invalid_email_origin$"):
        NotificationEmailRenderer().render("booking.confirmed", tenant_origin=origin)


def test_email_renderer_rejects_unsupported_event() -> None:
    with pytest.raises(ValueError, match=r"^unsupported_email_event$"):
        NotificationEmailRenderer().render("auth.password_reset", tenant_origin=TENANT_ORIGIN)


@pytest.mark.parametrize("security", ["plain", "starttls", "tls"])
async def test_smtp_sends_multipart_with_explicit_security_and_stable_message_id(
    security: Literal["plain", "starttls", "tls"], monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = Mock(spec=smtplib.SMTP)
    smtp = Mock(return_value=connection)
    smtp_ssl = Mock(return_value=connection)
    monkeypatch.setattr(smtplib, "SMTP", smtp)
    monkeypatch.setattr(smtplib, "SMTP_SSL", smtp_ssl)
    credentials = (
        {"username": "smtp-user", "password": "smtp-password"} if security != "plain" else {}
    )
    sender = SmtpEmailSender(
        host="smtp.example.test",
        port=1025,
        from_address=SENDER,
        timeout_seconds=2.5,
        security=security,
        **credentials,
    )
    rendered = NotificationEmailRenderer().render("booking.confirmed", tenant_origin=TENANT_ORIGIN)
    message_id = uuid4()

    await sender.send(recipient=RECIPIENT, email=rendered, message_id=message_id)
    await sender.send(recipient=RECIPIENT, email=rendered, message_id=message_id)

    first, second = (mock_call.args[0] for mock_call in connection.send_message.call_args_list)
    assert isinstance(first, EmailMessage)
    assert isinstance(second, EmailMessage)
    assert first["Message-ID"] == second["Message-ID"] == f"<{message_id}@example.test>"
    assert first["From"] == SENDER
    assert first["To"] == RECIPIENT
    assert first["Subject"] == rendered.subject
    assert first.get_content_type() == "multipart/alternative"
    plain = first.get_body(preferencelist=("plain",))
    html = first.get_body(preferencelist=("html",))
    assert plain is not None and plain.get_content().strip() == rendered.text
    assert html is not None and html.get_content().strip() == rendered.html

    if security == "tls":
        smtp.assert_not_called()
        tls_context = smtp_ssl.call_args.kwargs["context"]
        assert (
            smtp_ssl.call_args_list
            == [call("smtp.example.test", 1025, timeout=2.5, context=tls_context)] * 2
        )
    else:
        smtp_ssl.assert_not_called()
        assert smtp.call_args_list == [call("smtp.example.test", 1025, timeout=2.5)] * 2
        tls_context = (
            connection.starttls.call_args.kwargs["context"] if security == "starttls" else None
        )

    handshake = [call.starttls(context=tls_context)] if security == "starttls" else []
    login = [call.login("smtp-user", "smtp-password")] if security != "plain" else []
    if tls_context is not None:
        assert tls_context.check_hostname
        assert tls_context.verify_mode == ssl.CERT_REQUIRED
    assert connection.method_calls == [
        *handshake,
        *login,
        call.send_message(first),
        call.quit(),
        call.close(),
        *handshake,
        *login,
        call.send_message(second),
        call.quit(),
        call.close(),
    ]


def test_smtp_disallows_cleartext_credentials() -> None:
    with pytest.raises(ValueError, match=r"^smtp_authentication_requires_tls$"):
        SmtpEmailSender(
            host="smtp.example.test",
            port=1025,
            from_address=SENDER,
            timeout_seconds=2.5,
            security="plain",
            username="smtp-user",
            password="smtp-password",
        )


async def test_smtp_sanitizes_data_failure_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Mock(spec=smtplib.SMTP)
    connection.send_message.side_effect = smtplib.SMTPDataError(550, b"private server response")
    monkeypatch.setattr(smtplib, "SMTP", Mock(return_value=connection))
    sender = SmtpEmailSender(
        host="smtp.example.test",
        port=1025,
        from_address=SENDER,
        timeout_seconds=2.5,
        security="plain",
    )

    with pytest.raises(SmtpDeliveryError, match=r"^smtp_delivery_failed$"):
        await sender.send(
            recipient=RECIPIENT,
            email=RenderedEmail("Subject", "Plain text", "<p>HTML</p>"),
            message_id=uuid4(),
        )

    connection.quit.assert_not_called()
    connection.close.assert_called_once()


async def test_smtp_quit_disconnect_after_accepting_data_keeps_send_successful(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = Mock(spec=smtplib.SMTP)
    connection.quit.side_effect = smtplib.SMTPServerDisconnected("server closed connection")
    monkeypatch.setattr(smtplib, "SMTP", Mock(return_value=connection))
    sender = SmtpEmailSender(
        host="smtp.example.test",
        port=1025,
        from_address=SENDER,
        timeout_seconds=2.5,
        security="plain",
    )

    await sender.send(
        recipient=RECIPIENT,
        email=RenderedEmail("Subject", "Plain text", "<p>HTML</p>"),
        message_id=uuid4(),
    )

    connection.send_message.assert_called_once()
    connection.close.assert_called_once()


@pytest.mark.parametrize(
    "recipient",
    [
        "invalid@",
        "one@example..test",
        "one(comment)@example.test",
        "one@example.test, two@example.test",
    ],
)
async def test_smtp_rejects_invalid_envelope_recipient(
    recipient: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    smtp = Mock()
    monkeypatch.setattr(smtplib, "SMTP", smtp)
    sender = SmtpEmailSender(
        host="smtp.example.test",
        port=1025,
        from_address=SENDER,
        timeout_seconds=2.5,
        security="plain",
    )

    with pytest.raises(ValueError, match=r"^invalid_email_address$"):
        await sender.send(
            recipient=recipient,
            email=RenderedEmail("Subject", "Plain text", "<p>HTML</p>"),
            message_id=uuid4(),
        )

    smtp.assert_not_called()
