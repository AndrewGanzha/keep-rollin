class CatalogDomainError(Exception):
    """Base catalog domain error."""


class InvalidSlugError(CatalogDomainError):
    pass


class InvalidNameError(CatalogDomainError):
    pass


class InvalidMoneyError(CatalogDomainError):
    pass


class InvalidBatteryCountError(CatalogDomainError):
    pass


class InvalidAllowedDurationsError(CatalogDomainError):
    pass


class InvalidPriceTierError(CatalogDomainError):
    pass


class InvalidTimeRangeError(CatalogDomainError):
    pass


class InvalidOccupancyError(CatalogDomainError):
    pass


class OccupancyConflictError(CatalogDomainError):
    pass


class LotUnavailableError(CatalogDomainError):
    pass


class LotHasActiveRentalError(CatalogDomainError):
    pass
