from collections.abc import Mapping
from typing import Any, Self, TypeVar

from pydantic import BaseModel, ConfigDict, RootModel

T = TypeVar("T")


class FrozenModel(BaseModel):
    """Base model that cannot be updated or constructed outside validation."""

    model_config = ConfigDict(frozen=True, strict=True)

    @classmethod
    def model_validate(  # type: ignore[override]
        cls,
        obj: Any,
        *,
        strict: bool | None = None,
        from_attributes: bool | None = None,
        context: Any | None = None,
    ) -> Self:
        return super().model_validate(
            obj,
            strict=True,
            from_attributes=from_attributes,
            context=context,
        )

    @classmethod
    def model_validate_json(  # type: ignore[override]
        cls,
        json_data: Any,
        *,
        strict: bool | None = None,
        context: Any | None = None,
    ) -> Self:
        raise TypeError("Value objects must be constructed through create()")

    @classmethod
    def model_validate_strings(  # type: ignore[override]
        cls,
        obj: Any,
        *,
        strict: bool | None = None,
        context: Any | None = None,
    ) -> Self:
        raise TypeError("Value objects must be constructed through create()")

    @classmethod
    def model_construct(  # type: ignore[override]
        cls, _fields_set: set[str] | None = None, **values: Any
    ) -> Self:
        raise TypeError("Value objects must be constructed through create()")

    @classmethod
    def construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Self:
        raise TypeError("Value objects must be constructed through create()")

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        if update:
            raise TypeError("Value objects cannot be updated in place")
        return super().model_copy(deep=deep)

    def copy(
        self,
        *,
        include: Any = None,
        exclude: Any = None,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        raise TypeError("Value objects must be constructed through create()")


class FrozenRootModel(RootModel[T]):
    """Frozen root value object with guarded construction helpers."""

    model_config = ConfigDict(frozen=True, strict=True)

    @classmethod
    def model_validate(  # type: ignore[override]
        cls,
        obj: Any,
        *,
        strict: bool | None = None,
        from_attributes: bool | None = None,
        context: Any | None = None,
    ) -> Self:
        return super().model_validate(
            obj,
            strict=True,
            from_attributes=from_attributes,
            context=context,
        )

    @classmethod
    def model_validate_json(  # type: ignore[override]
        cls,
        json_data: Any,
        *,
        strict: bool | None = None,
        context: Any | None = None,
    ) -> Self:
        raise TypeError("Value objects must be constructed through create()")

    @classmethod
    def model_validate_strings(  # type: ignore[override]
        cls,
        obj: Any,
        *,
        strict: bool | None = None,
        context: Any | None = None,
    ) -> Self:
        raise TypeError("Value objects must be constructed through create()")

    @classmethod
    def model_construct(  # type: ignore[override]
        cls, _fields_set: set[str] | None = None, **values: Any
    ) -> Self:
        raise TypeError("Value objects must be constructed through create()")

    @classmethod
    def construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Self:
        raise TypeError("Value objects must be constructed through create()")

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        if update:
            raise TypeError("Value objects cannot be updated in place")
        return super().model_copy(deep=deep)

    def copy(
        self,
        *,
        include: Any = None,
        exclude: Any = None,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        raise TypeError("Value objects must be constructed through create()")
