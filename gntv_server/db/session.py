from collections.abc import AsyncIterator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from gntv_server.core.config import get_settings


def make_async_database_url(database_url: str) -> str:
    url = make_url(database_url)

    drivername = url.drivername
    if drivername == "postgres":
        drivername = "postgresql+asyncpg"
    elif drivername == "postgresql":
        drivername = "postgresql+asyncpg"
    elif drivername == "postgresql+psycopg":
        drivername = "postgresql+asyncpg"

    return url.set(drivername=drivername).render_as_string(hide_password=False)


def create_engine(database_url: str | None = None) -> AsyncEngine:
    settings = get_settings()
    url = make_async_database_url(database_url or settings.database_url)
    return create_async_engine(url, pool_pre_ping=True)


engine = create_engine()
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
