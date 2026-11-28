from datetime import date, datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from src.domain.entities.user_account import VerificationStatus
from src.domain.value_objects.limits import MAX_DATABASE_INTEGER

VerificationDocumentPurpose = Literal[
    "verification_passport", "verification_registration", "verification_selfie"
]
VerificationDecision = Literal["approved", "rejected"]


def _valid_text(value: str) -> str:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("text must contain valid Unicode") from None
    if "\x00" in value:
        raise ValueError("NUL characters are not allowed")
    return value


class VerificationPassport(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, str_strip_whitespace=True)

    full_name: Annotated[str, Field(min_length=1, max_length=200), AfterValidator(_valid_text)] = (
        Field(repr=False)
    )
    birth_date: date = Field(repr=False)
    passport_number: Annotated[
        str, Field(min_length=1, max_length=64), AfterValidator(_valid_text)
    ] = Field(repr=False)
    issued_by: Annotated[str, Field(min_length=1, max_length=300), AfterValidator(_valid_text)] = (
        Field(repr=False)
    )


class VerificationDocumentsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    verification_passport: UUID
    verification_registration: UUID
    verification_selfie: UUID

    def by_purpose(self) -> dict[VerificationDocumentPurpose, UUID]:
        return {
            "verification_passport": self.verification_passport,
            "verification_registration": self.verification_registration,
            "verification_selfie": self.verification_selfie,
        }


class CreateVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    passport: VerificationPassport = Field(repr=False)
    documents: VerificationDocumentsInput = Field(repr=False)


class VerificationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    decision: VerificationDecision
    comment: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, max_length=2000),
            AfterValidator(_valid_text),
        ]
        | None
    ) = Field(default=None, repr=False)
    version: int = Field(strict=True, ge=1, le=MAX_DATABASE_INTEGER)


class VerificationRequestSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: VerificationStatus
    admin_comment: str | None = Field(repr=False)
    created_at: datetime
    reviewed_at: datetime | None
    version: int


class AdminUserRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    email: str


class AdminVerificationRequestSummary(VerificationRequestSummary):
    user: AdminUserRef

    @classmethod
    def from_summary(cls, summary: VerificationRequestSummary, user: AdminUserRef) -> Self:
        return cls(**summary.model_dump(), user=user)


class VerificationDocument(BaseModel):
    purpose: VerificationDocumentPurpose
    url: str = Field(repr=False, json_schema_extra={"format": "uri"})


class MyVerificationRequest(VerificationRequestSummary):
    documents: list[VerificationDocument] = Field(repr=False)


class VerificationRequest(AdminVerificationRequestSummary):
    passport: VerificationPassport = Field(repr=False)
    documents: list[VerificationDocument] = Field(repr=False)


class VerificationRequestPage[T: VerificationRequestSummary](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
