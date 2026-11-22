from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the ASGI application with explicit configuration."""
    resolved_settings = settings or get_settings()
    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
    )
    application.state.settings = resolved_settings
    application.include_router(health_router)
    return application


app = create_app()
