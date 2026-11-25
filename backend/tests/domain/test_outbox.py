from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.domain.entities.outbox_message import OutboxError, OutboxMessage

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_outbox_message_validates_fields_and_payload() -> None:
    message = OutboxMessage(
        id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
        event_type="booking.confirmed",
        entity_id=uuid4(),
        user_id=None,
        channel="email",
        payload={"rental_id": "x"},
        status="pending",
        attempts=0,
        available_at=NOW,
        last_error=None,
        processed_at=None,
    )
    assert message.payload["rental_id"] == "x"

    with pytest.raises(OutboxError):
        OutboxMessage(
            id=uuid4(),
            created_at=NOW,
            updated_at=NOW,
            event_type="",
            entity_id=None,
            user_id=None,
            channel=None,
            payload={},
            status="pending",
            attempts=0,
            available_at=NOW,
            last_error=None,
            processed_at=None,
        )
    with pytest.raises(OutboxError):
        OutboxMessage(
            id=uuid4(),
            created_at=NOW,
            updated_at=NOW,
            event_type="event",
            entity_id=None,
            user_id=None,
            channel=None,
            payload={},
            status="pending",
            attempts=-1,
            available_at=NOW,
            last_error=None,
            processed_at=None,
        )
