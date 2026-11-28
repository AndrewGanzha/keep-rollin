import re
from dataclasses import dataclass

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

_HOST_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HTTPS_ORIGIN = re.compile(rf"https://{_HOST_LABEL}(?:\.{_HOST_LABEL})*")
_ACCOUNT_RENTALS = "/account/rentals"
_ACCOUNT_TICKETS = "/account/tickets"


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    text: str
    html: str


@dataclass(frozen=True)
class _Notification:
    subject: str
    text: str
    path: str
    action: str


_NOTIFICATIONS = {
    "verification.approved": _Notification(
        "Верификация пройдена",
        "Ваша заявка одобрена. Теперь вы можете бронировать.",
        "/account/verification",
        "Открыть статус верификации",
    ),
    "verification.rejected": _Notification(
        "Заявка на верификацию отклонена",
        "Ваша заявка на верификацию отклонена.",
        "/account/verification",
        "Открыть статус верификации",
    ),
    "booking.confirmed": _Notification(
        "Бронь подтверждена",
        "Ваша бронь подтверждена. Время начала и окончания указано в личном кабинете.",
        _ACCOUNT_RENTALS,
        "Открыть мои аренды",
    ),
    "rental.closed": _Notification(
        "Аренда завершена",
        "Подробности завершённой аренды доступны в личном кабинете.",
        _ACCOUNT_RENTALS,
        "Открыть мои аренды",
    ),
    "booking.cancelled": _Notification(
        "Бронь отменена",
        "Статус отменённой брони можно проверить в личном кабинете.",
        _ACCOUNT_RENTALS,
        "Открыть мои аренды",
    ),
    "rental.ending_soon": _Notification(
        "Аренда скоро закончится",
        "Проверьте время окончания аренды и подготовьтесь вернуть оборудование.",
        _ACCOUNT_RENTALS,
        "Открыть мои аренды",
    ),
    "rental.overdue.user": _Notification(
        "Срок аренды истёк",
        "Срок аренды истёк. Пожалуйста, верните оборудование как можно скорее.",
        _ACCOUNT_RENTALS,
        "Открыть мои аренды",
    ),
    "rental.overdue.admin": _Notification(
        "Аренда просрочена",
        "Новая просроченная аренда появилась в панели администратора.",
        "/admin/rentals",
        "Открыть список аренд",
    ),
    "ticket.created.admin": _Notification(
        "Новое обращение арендатора",
        "Арендатор сообщил, что возникла неполадка. Проверьте обращение в панели администратора.",
        "/admin/tickets",
        "Открыть список обращений",
    ),
    "ticket.updated.user": _Notification(
        "Статус обращения изменился",
        "Актуальный статус обращения доступен в личном кабинете.",
        _ACCOUNT_TICKETS,
        "Открыть мои обращения",
    ),
    "ticket.resolved.user": _Notification(
        "Обращение решено",
        "Ваше обращение закрыто. Ответ доступен в личном кабинете.",
        _ACCOUNT_TICKETS,
        "Открыть мои обращения",
    ),
}
EMAIL_EVENT_TYPES = frozenset(_NOTIFICATIONS)


def push_content(event_type: str) -> tuple[str, str, str]:
    notification = _NOTIFICATIONS[event_type]
    return notification.subject, notification.text, notification.path


class NotificationEmailRenderer:
    def __init__(self) -> None:
        environment = Environment(
            loader=PackageLoader("src.infrastructure.email"),
            autoescape=select_autoescape(),
            undefined=StrictUndefined,
        )
        self._text_template = environment.get_template("notification.txt")
        self._html_template = environment.get_template("notification.html")

    def render(self, event_type: str, *, tenant_origin: str) -> RenderedEmail:
        notification = _NOTIFICATIONS.get(event_type)
        if notification is None:
            raise ValueError("unsupported_email_event")
        if not _HTTPS_ORIGIN.fullmatch(tenant_origin):
            raise ValueError("invalid_email_origin")

        context = {
            "subject": notification.subject,
            "text": notification.text,
            "action": notification.action,
            "link": f"{tenant_origin}{notification.path}",
        }
        return RenderedEmail(
            subject=notification.subject,
            text=self._text_template.render(context),
            html=self._html_template.render(context),
        )
