from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.postgres.base import Base


class BatteryStockRecord(Base):
    __tablename__ = "battery_stock"
    __table_args__ = (
        UniqueConstraint("tenant_id", "battery_type", name="uq_battery_stock_tenant_type"),
        CheckConstraint("btrim(battery_type) <> ''", name="battery_type"),
        CheckConstraint("btrim(name) <> ''", name="name"),
        CheckConstraint("quantity >= 0", name="quantity"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False
    )
    battery_type: Mapped[str] = mapped_column(Text(), nullable=False)
    name: Mapped[str] = mapped_column(Text(), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger(), nullable=False)
