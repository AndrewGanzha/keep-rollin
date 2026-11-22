from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.health import router as health_router
from app.config import Settings, get_settings
from app.db import create_engine, create_session_factory
from app.errors import register_exception_handlers
from app.logging import configure_logging
from app.middleware import RequestContextMiddleware, TenantMiddleware
from app.tenancy import DatabaseTenantResolver, TenantResolver


def create_app(
    settings: Settings | None = None,
    tenant_resolver: TenantResolver | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    """Create the ASGI application with explicit configuration."""
    resolved_settings = settings or get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = None
        factory = session_factory
        resolver = tenant_resolver

        if factory is None and resolved_settings.database_url:
            try:
                engine = create_engine(resolved_settings.database_url)
                factory = create_session_factory(engine)
            except Exception:
                # A malformed DSN must not make liveness unavailable. Tenant
                # requests stay unavailable and readiness reports the failure.
                engine = None
                factory = None
        if resolver is None and factory is not None:
            resolver = DatabaseTenantResolver(factory, resolved_settings.database_role)

        application.state.engine = engine
        application.state.session_factory = factory
        application.state.tenant_resolver = resolver
        try:
            yield
        finally:
            if engine is not None:
                await engine.dispose()

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.tenant_resolver = tenant_resolver
    application.state.session_factory = session_factory

    register_exception_handlers(application)
    application.add_middleware(TenantMiddleware)
    application.add_middleware(RequestContextMiddleware)
    application.include_router(health_router)
    return application


app = create_app()
