from dataclasses import dataclass

from polyfactory.factories import DataclassFactory


@dataclass(frozen=True)
class TenantSeed:
    name: str
    slug: str
    domain: str
    subdomain: str


@dataclass(frozen=True)
class UserSeed:
    email: str
    name: str
    role: str


class TenantSeedFactory(DataclassFactory[TenantSeed]):
    __model__ = TenantSeed


class UserSeedFactory(DataclassFactory[UserSeed]):
    __model__ = UserSeed
