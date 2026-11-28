"""Catalog ORM records."""

from src.infrastructure.postgres.models.audit_log_record import AuditLogRecord
from src.infrastructure.postgres.models.battery_stock_record import BatteryStockRecord
from src.infrastructure.postgres.models.category_record import CategoryRecord
from src.infrastructure.postgres.models.characteristic_record import CharacteristicRecord
from src.infrastructure.postgres.models.file_record import AttachmentRecord, FileRecord
from src.infrastructure.postgres.models.idempotency_key_record import IdempotencyKeyRecord
from src.infrastructure.postgres.models.lot_price_tier_record import LotPriceTierRecord
from src.infrastructure.postgres.models.lot_record import LotRecord
from src.infrastructure.postgres.models.lot_variant_record import LotVariantRecord
from src.infrastructure.postgres.models.mfa_challenge_record import MfaChallengeRecord
from src.infrastructure.postgres.models.occupancy_record import OccupancyRecord
from src.infrastructure.postgres.models.offer_acceptance_record import OfferAcceptanceRecord
from src.infrastructure.postgres.models.offer_version_record import OfferVersionRecord
from src.infrastructure.postgres.models.outbox_message_record import OutboxMessageRecord
from src.infrastructure.postgres.models.password_reset_token_record import (
    PasswordResetTokenRecord,
)
from src.infrastructure.postgres.models.refresh_session_record import RefreshSessionRecord
from src.infrastructure.postgres.models.rental_record import RentalRecord
from src.infrastructure.postgres.models.tenant_settings_record import TenantSettingsRecord
from src.infrastructure.postgres.models.ticket_record import TicketAttachmentRecord, TicketRecord
from src.infrastructure.postgres.models.verification_request_record import (
    VerificationDocumentRecord,
    VerificationRequestRecord,
)

__all__ = [
    "AttachmentRecord",
    "AuditLogRecord",
    "BatteryStockRecord",
    "CategoryRecord",
    "CharacteristicRecord",
    "FileRecord",
    "IdempotencyKeyRecord",
    "LotPriceTierRecord",
    "LotRecord",
    "LotVariantRecord",
    "MfaChallengeRecord",
    "OccupancyRecord",
    "OfferAcceptanceRecord",
    "OfferVersionRecord",
    "OutboxMessageRecord",
    "PasswordResetTokenRecord",
    "RefreshSessionRecord",
    "RentalRecord",
    "TenantSettingsRecord",
    "TicketAttachmentRecord",
    "TicketRecord",
    "VerificationDocumentRecord",
    "VerificationRequestRecord",
]
