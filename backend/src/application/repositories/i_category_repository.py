from abc import ABC, abstractmethod

from src.domain.entities.category import Category


class ICategoryRepository(ABC):
    @abstractmethod
    async def list_active(self) -> list[Category]:
        raise NotImplementedError
