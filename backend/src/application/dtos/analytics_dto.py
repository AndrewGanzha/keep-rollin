from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from src.application.dtos.verification_dto import AdminUserRef
from src.infrastructure.postgres.models.rental_record import RentalStatus

AnalyticsGroupBy = Literal["category", "lot", "day"]


class AnalyticsMetrics(BaseModel):
    revenue_minor: int
    rentals_count: int
    cancelled_count: int
    overdue_count: int
    avg_rental_minor: int
    utilization_pct: float


class AnalyticsSummary(AnalyticsMetrics):
    period_from: datetime = Field(serialization_alias="from")
    period_to: datetime = Field(serialization_alias="to")


class AnalyticsBucket(BaseModel):
    key: str
    label: str
    rentals_count: int
    cancelled_count: int
    revenue_minor: int
    utilization_pct: float


class AnalyticsRevenue(BaseModel):
    group_by: AnalyticsGroupBy
    buckets: list[AnalyticsBucket]


class AnalyticsLotRef(BaseModel):
    id: UUID
    name: str


class AnalyticsRental(BaseModel):
    id: UUID
    start_time: datetime
    end_time: datetime
    status: RentalStatus
    price_minor: int
    currency: str
    user: AdminUserRef


class AnalyticsLotDetail(BaseModel):
    lot: AnalyticsLotRef
    period_from: datetime = Field(serialization_alias="from")
    period_to: datetime = Field(serialization_alias="to")
    summary: AnalyticsSummary
    daily: list[AnalyticsBucket]
    rentals: list[AnalyticsRental]
    rentals_total: int


class AnalyticsComparison(BaseModel):
    current: AnalyticsSummary
    previous: AnalyticsSummary
    delta: AnalyticsMetrics


class AnalyticsExportRow(BaseModel):
    id: UUID
    lot_name: str
    category_name: str
    start_time: datetime
    end_time: datetime
    status: RentalStatus
    price_minor: int
    currency: str
