from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.admin_audit import router as admin_audit_router
from app.api.admin_batteries import router as admin_batteries_router
from app.api.admin_calendar import router as admin_calendar_router
from app.api.admin_categories import router as admin_categories_router
from app.api.admin_lots import router as admin_lots_router
from app.api.admin_offers import router as admin_offers_router
from app.api.admin_settings import router as admin_settings_router
from app.api.admin_users import router as admin_users_router
from app.api.auth import router as auth_router
from app.api.auth_deps import get_password_hasher
from app.api.availability import router as availability_router
from app.api.catalog import router as catalog_router
from app.api.files import UploadLengthMiddleware
from app.api.files import router as files_router
from app.api.health import router as health_router
from app.api.offers import me_router as me_offers_router
from app.api.offers import public_router as public_offers_router
from app.api.quote import router as quote_router
from app.api.rental_reads import admin_router as admin_rental_reads_router
from app.api.rental_reads import me_router as me_rental_reads_router
from app.api.rentals import admin_router as admin_rentals_router
from app.api.rentals import router as rentals_router
from app.api.tenant import router as tenant_router
from app.api.verification import admin_router as admin_verification_router
from app.api.verification import me_router as me_verification_router
from app.config import Settings, get_settings
from app.db import create_engine, create_session_factory
from app.errors import register_exception_handlers
from app.logging import configure_logging
from app.middleware import RequestContextMiddleware, TenantMiddleware
from app.tenancy import DatabaseTenantResolver, TenantResolver
from src.application.services.rate_limit import SlidingWindowRateLimiter
from src.infrastructure.security.secret_box import CodeHasher, SecretBox


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
        get_password_hasher()
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
    security_secret = resolved_settings.security_key or resolved_settings.jwt_secret
    application.state.secret_box = SecretBox.from_settings(
        security_secret,
        key_id=resolved_settings.security_key_id,
        previous_keys=resolved_settings.security_previous_keys,
    )
    application.state.code_hasher = CodeHasher(security_secret)
    application.state.login_ip_limiter = SlidingWindowRateLimiter(
        limit=resolved_settings.auth_rate_limit_per_minute,
        window_seconds=resolved_settings.auth_rate_limit_window_seconds,
    )
    application.state.login_email_limiter = SlidingWindowRateLimiter(
        limit=resolved_settings.auth_rate_limit_email_per_minute,
        window_seconds=resolved_settings.auth_rate_limit_window_seconds,
    )

    register_exception_handlers(application)
    application.add_middleware(TenantMiddleware)
    application.add_middleware(UploadLengthMiddleware)
    application.add_middleware(RequestContextMiddleware)
    application.include_router(health_router)
    application.include_router(files_router)
    application.include_router(auth_router)
    application.include_router(admin_calendar_router)
    application.include_router(admin_categories_router)
    application.include_router(admin_audit_router)
    application.include_router(admin_batteries_router)
    application.include_router(admin_settings_router)
    application.include_router(admin_users_router)
    application.include_router(admin_offers_router)
    application.include_router(admin_lots_router)
    application.include_router(catalog_router)
    application.include_router(public_offers_router)
    application.include_router(me_offers_router)
    application.include_router(me_verification_router)
    application.include_router(admin_verification_router)
    application.include_router(availability_router)
    application.include_router(quote_router)
    application.include_router(rentals_router)
    application.include_router(admin_rentals_router)
    application.include_router(me_rental_reads_router)
    application.include_router(admin_rental_reads_router)
    application.include_router(tenant_router)
    return application


app = create_app()
