from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.application.services.audit import (
    AuditEntry,
    AuditError,
    AuditWriter,
    validate_audit_event,
)


class RecordingAuditRepository:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def add(self, entry: AuditEntry) -> None:
        self.entries.append(entry)

    async def list_entries(self, **kwargs: object) -> list[AuditEntry]:
        return self.entries

    async def purge_before(self, **kwargs: object) -> int:
        return 0


def test_valid_staff_event_is_accepted() -> None:
    validate_audit_event(
        action="admin.created",
        actor_id=uuid4(),
        actor_role="owner",
        entity_type="user",
        metadata={"role": "admin"},
        ip="127.0.0.1",
        request_id="req-1",
    )


def test_system_event_requires_no_actor() -> None:
    validate_audit_event(
        action="tenant.provisioned",
        actor_id=None,
        actor_role="platform",
        entity_type="tenant",
        metadata={"source": "cli"},
        ip=None,
        request_id=None,
    )
    with pytest.raises(AuditError):
        validate_audit_event(
            action="tenant.provisioned",
            actor_id=uuid4(),
            actor_role="platform",
            entity_type="tenant",
            metadata={"source": "cli"},
            ip=None,
            request_id=None,
        )
    with pytest.raises(AuditError):
        validate_audit_event(
            action="admin.created",
            actor_id=None,
            actor_role="owner",
            entity_type="user",
            metadata={"role": "admin"},
            ip=None,
            request_id=None,
        )


@pytest.mark.parametrize(
    "metadata",
    [
        {"email": "owner@example.com"},
        {"role": "owner@example.com"},
        {"role": "reset-token"},
        {"role": "password"},
        {"role": "x" * 300},
    ],
)
def test_pii_and_secret_like_metadata_is_rejected(metadata: dict[str, object]) -> None:
    with pytest.raises(AuditError):
        validate_audit_event(
            action="admin.created",
            actor_id=uuid4(),
            actor_role="owner",
            entity_type="user",
            metadata=metadata,
            ip=None,
            request_id=None,
        )


def test_unknown_action_entity_and_ip_are_rejected() -> None:
    with pytest.raises(AuditError):
        validate_audit_event(
            action="unknown.action",
            actor_id=uuid4(),
            actor_role="owner",
            entity_type="user",
            metadata={},
            ip=None,
            request_id=None,
        )
    with pytest.raises(AuditError):
        validate_audit_event(
            action="admin.created",
            actor_id=uuid4(),
            actor_role="owner",
            entity_type="unknown",
            metadata={"role": "admin"},
            ip=None,
            request_id=None,
        )
    validate_audit_event(
        action="admin.created",
        actor_id=uuid4(),
        actor_role="owner",
        entity_type="user",
        metadata={"role": "admin"},
        ip="not-an-ip",
        request_id=None,
    )


def test_status_and_changed_field_allowlists_are_action_specific() -> None:
    with pytest.raises(AuditError):
        validate_audit_event(
            action="verification.decided",
            actor_id=uuid4(),
            actor_role="admin",
            entity_type="verification_request",
            metadata={"decision": "active"},
            ip=None,
            request_id=None,
        )
    with pytest.raises(AuditError):
        validate_audit_event(
            action="settings.updated",
            actor_id=uuid4(),
            actor_role="owner",
            entity_type="tenant_settings",
            metadata={"changed_fields": ["sk_live_secret"]},
            ip=None,
            request_id=None,
        )
    validate_audit_event(
        action="settings.updated",
        actor_id=uuid4(),
        actor_role="owner",
        entity_type="tenant_settings",
        metadata={"changed_fields": ["policies", "currency"]},
        ip=None,
        request_id=None,
    )
    validate_audit_event(
        action="verification.decided",
        actor_id=uuid4(),
        actor_role="admin",
        entity_type="verification_request",
        metadata={"decision": "approved"},
        ip=None,
        request_id=None,
    )


async def test_writer_adds_entry_without_committing() -> None:
    repository = RecordingAuditRepository()
    tenant_id = uuid4()
    actor_id = uuid4()
    writer = AuditWriter(repository, tenant_id=tenant_id)
    entry = await writer.record(
        action="admin.created",
        actor_id=actor_id,
        actor_role="owner",
        entity_type="user",
        entity_id=uuid4(),
        metadata={"role": "admin"},
        ip="testclient",
        request_id="req-2",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert repository.entries == [entry]
    assert entry.tenant_id == tenant_id
    assert entry.metadata == {"role": "admin"}
    assert entry.ip is None
