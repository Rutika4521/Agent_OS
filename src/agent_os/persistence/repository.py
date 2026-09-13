"""Agent-OS Persistence — Repository."""
from sqlalchemy import select
from agent_os.persistence.database import DatabaseManager
from agent_os.persistence.models import (
    ProcessRecord, ProcessMetricRecord, ContextPageRecord, CheckpointRecord,
    MessageRecord, EventRecord, ResourceUsageRecord, FailureDBRecord
)

class Repository:
    def __init__(self, db_manager: DatabaseManager):
        self._db = db_manager

    async def save_process(self, process_data: dict) -> None:
        async with self._db.get_session() as session:
            record = ProcessRecord(**process_data)
            session.add(record)
            await session.commit()

    async def get_process(self, process_id: int) -> dict | None:
        async with self._db.get_session() as session:
            result = await session.execute(select(ProcessRecord).where(ProcessRecord.process_id == process_id))
            record = result.scalar_one_or_none()
            if record:
                return {c.name: getattr(record, c.name) for c in record.__table__.columns}
            return None

    async def list_processes(self) -> list[dict]:
        async with self._db.get_session() as session:
            result = await session.execute(select(ProcessRecord))
            records = result.scalars().all()
            return [{c.name: getattr(record, c.name) for c in record.__table__.columns} for record in records]

    async def save_event(self, event_data: dict) -> None:
        async with self._db.get_session() as session:
            record = EventRecord(**event_data)
            session.add(record)
            await session.commit()

    async def get_events(self, event_type: str | None = None, process_id: int | None = None, limit: int = 100) -> list[dict]:
        async with self._db.get_session() as session:
            query = select(EventRecord)
            if event_type:
                query = query.where(EventRecord.event_type == event_type)
            if process_id is not None:
                query = query.where(EventRecord.process_id == process_id)
            query = query.limit(limit)
            result = await session.execute(query)
            records = result.scalars().all()
            return [{c.name: getattr(record, c.name) for c in record.__table__.columns} for record in records]

    async def save_message(self, message_data: dict) -> None:
        async with self._db.get_session() as session:
            record = MessageRecord(**message_data)
            session.add(record)
            await session.commit()

    async def save_checkpoint(self, checkpoint_data: dict) -> None:
        async with self._db.get_session() as session:
            record = CheckpointRecord(**checkpoint_data)
            session.add(record)
            await session.commit()

    async def get_checkpoint(self, checkpoint_id: str) -> dict | None:
        async with self._db.get_session() as session:
            result = await session.execute(select(CheckpointRecord).where(CheckpointRecord.checkpoint_id == checkpoint_id))
            record = result.scalar_one_or_none()
            if record:
                return {c.name: getattr(record, c.name) for c in record.__table__.columns}
            return None

    async def save_failure(self, failure_data: dict) -> None:
        async with self._db.get_session() as session:
            record = FailureDBRecord(**failure_data)
            session.add(record)
            await session.commit()

    async def save_metrics(self, metrics_data: dict) -> None:
        async with self._db.get_session() as session:
            record = ProcessMetricRecord(**metrics_data)
            session.add(record)
            await session.commit()

    async def get_process_metrics(self, process_id: int) -> list[dict]:
        async with self._db.get_session() as session:
            result = await session.execute(select(ProcessMetricRecord).where(ProcessMetricRecord.process_id == process_id))
            records = result.scalars().all()
            return [{c.name: getattr(record, c.name) for c in record.__table__.columns} for record in records]
