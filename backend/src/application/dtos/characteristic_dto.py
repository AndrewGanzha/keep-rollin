from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel

from src.domain.entities.characteristic import Characteristic

CharacteristicType = Literal["number", "text", "select"]


class CharacteristicDTO(BaseModel):
    id: UUID
    code: str
    name: str
    type: CharacteristicType
    unit: str | None
    is_required: bool
    options: list[str]
    sort: int

    @classmethod
    def from_domain(cls, characteristic: Characteristic) -> Self:
        return cls(
            id=characteristic.id,
            code=characteristic.code.value,
            name=characteristic.name.value,
            type=characteristic.type,
            unit=characteristic.unit,
            is_required=characteristic.is_required,
            options=list(characteristic.options),
            sort=characteristic.sort,
        )
