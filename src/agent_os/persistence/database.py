"""Agent-OS Persistence — Database manager."""
from __future__ import annotations
import json
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

class DatabaseManager:
    def __init__(self, database_url: str = "sqlite+aiosqlite:///agent_os.db"):
        self._database_url = database_url
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
    
    async def initialize(self) -> None:
        self._engine = create_async_engine(self._database_url, echo=False)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        async with self._engine.begin() as conn:
            from agent_os.persistence.models import Base as ModelBase
            await conn.run_sync(ModelBase.metadata.create_all)
    
    def get_session(self) -> AsyncSession:
        if self._session_factory is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._session_factory()
    
    async def close(self) -> None:
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._session_factory = None
