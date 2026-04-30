from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# Engine and session factory are created lazily so that importing this module
# during testing does not require a live database. Tests override get_db via
# FastAPI's dependency_overrides instead.
_engine = None
_AsyncSessionLocal = None


def _get_engine():
    global _engine, _AsyncSessionLocal
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            echo=settings.environment == "development",
        )
        _AsyncSessionLocal = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine, _AsyncSessionLocal


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    _, session_factory = _get_engine()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
