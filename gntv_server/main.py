from fastapi import FastAPI

from gntv_server.api.admin import router as admin_router
from gntv_server.api.health import router as health_router
from gntv_server.api.tv import router as tv_router
from gntv_server.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.include_router(health_router)
    app.include_router(admin_router)
    app.include_router(tv_router)
    return app


app = create_app()
