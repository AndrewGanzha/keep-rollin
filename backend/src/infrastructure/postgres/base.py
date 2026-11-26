"""Shared SQLAlchemy metadata during the catalog slice.

Tenant and user records still live in ``app.models``; catalog records use the same
metadata so Alembic sees one schema. A later refactor can move the base and
tenant/user records into infrastructure without changing the database contract.
"""

from app.models import Base

__all__ = ["Base"]
