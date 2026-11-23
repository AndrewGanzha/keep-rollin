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
