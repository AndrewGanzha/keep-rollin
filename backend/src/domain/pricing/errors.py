from src.domain.exceptions import CatalogDomainError


class PricingError(CatalogDomainError):
    """Base pricing error."""


class RentalPeriodNotAllowedError(PricingError):
    """The requested duration is below the lot minimum."""
