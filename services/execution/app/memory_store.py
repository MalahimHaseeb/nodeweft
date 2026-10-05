from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import MemoryEntry


class MemoryStore(Protocol):
    async def claim(self, workflow_id: str, namespace: str, key: str, value: Any, run_id: str) -> bool: ...

    async def set(self, workflow_id: str, namespace: str, key: str, value: Any, run_id: str) -> None: ...

    async def get(self, workflow_id: str, namespace: str, key: str) -> Optional[dict]: ...

    async def list(self, workflow_id: str, namespace: str, limit: int) -> list[dict]: ...

    async def delete(self, workflow_id: str, namespace: str, key: str) -> bool: ...

    async def commit_run(self, run_id: str) -> None: ...

    async def release_run(self, run_id: str) -> None: ...


class PostgresMemoryStore:
    def __init__(self, session_factory: async_sessionmaker, stale_after_minutes: int):
        self._factory = session_factory
        self._stale_after = timedelta(minutes=stale_after_minutes)

    async def claim(self, workflow_id: str, namespace: str, key: str, value: Any, run_id: str) -> bool:
        stale_before = datetime.now(timezone.utc) - self._stale_after
        statement = (
            pg_insert(MemoryEntry)
            .values(workflow_id=workflow_id, namespace=namespace, key=key, value=value, status="pending", run_id=run_id)
            .on_conflict_do_update(
                constraint="uq_memory_entry",
                set_={"run_id": run_id, "value": value, "status": "pending", "updated_at": func.now()},
                where=and_(MemoryEntry.status == "pending", MemoryEntry.updated_at < stale_before),
            )
            .returning(MemoryEntry.id)
        )
        async with self._factory() as session:
            result = await session.execute(statement)
            claimed = result.first() is not None
            await session.commit()
        return claimed

    async def set(self, workflow_id: str, namespace: str, key: str, value: Any, run_id: str) -> None:
        statement = (
            pg_insert(MemoryEntry)
            .values(workflow_id=workflow_id, namespace=namespace, key=key, value=value, status="pending", run_id=run_id)
            .on_conflict_do_update(
                constraint="uq_memory_entry",
                set_={"value": value, "updated_at": func.now()},
            )
        )
        async with self._factory() as session:
            await session.execute(statement)
            await session.commit()

    async def get(self, workflow_id: str, namespace: str, key: str) -> Optional[dict]:
        async with self._factory() as session:
            result = await session.execute(
                select(MemoryEntry).where(
                    MemoryEntry.workflow_id == workflow_id,
                    MemoryEntry.namespace == namespace,
                    MemoryEntry.key == key,
                )
            )
            entry = result.scalar_one_or_none()
            return None if entry is None else {"key": entry.key, "value": entry.value, "status": entry.status}

    async def list(self, workflow_id: str, namespace: str, limit: int) -> list[dict]:
        async with self._factory() as session:
            result = await session.execute(
                select(MemoryEntry)
                .where(MemoryEntry.workflow_id == workflow_id, MemoryEntry.namespace == namespace)
                .order_by(MemoryEntry.updated_at.desc())
                .limit(limit)
            )
            return [
                {"key": entry.key, "value": entry.value, "status": entry.status, "updated_at": entry.updated_at}
                for entry in result.scalars()
            ]

    async def delete(self, workflow_id: str, namespace: str, key: str) -> bool:
        async with self._factory() as session:
            result = await session.execute(
                delete(MemoryEntry).where(
                    MemoryEntry.workflow_id == workflow_id,
                    MemoryEntry.namespace == namespace,
                    MemoryEntry.key == key,
                )
            )
            await session.commit()
            return result.rowcount > 0

    async def commit_run(self, run_id: str) -> None:
        async with self._factory() as session:
            await session.execute(
                update(MemoryEntry)
                .where(MemoryEntry.run_id == run_id, MemoryEntry.status == "pending")
                .values(status="committed", updated_at=func.now())
            )
            await session.commit()

    async def release_run(self, run_id: str) -> None:
        async with self._factory() as session:
            await session.execute(
                delete(MemoryEntry).where(MemoryEntry.run_id == run_id, MemoryEntry.status == "pending")
            )
            await session.commit()


class InMemoryMemoryStore:
    def __init__(self):
        self.entries: dict[tuple[str, str, str], dict] = {}

    async def claim(self, workflow_id: str, namespace: str, key: str, value: Any, run_id: str) -> bool:
        identity = (workflow_id, namespace, key)
        if identity in self.entries:
            return False
        self.entries[identity] = {"value": value, "status": "pending", "run_id": run_id}
        return True

    async def set(self, workflow_id: str, namespace: str, key: str, value: Any, run_id: str) -> None:
        identity = (workflow_id, namespace, key)
        if identity in self.entries:
            self.entries[identity]["value"] = value
        else:
            self.entries[identity] = {"value": value, "status": "pending", "run_id": run_id}

    async def get(self, workflow_id: str, namespace: str, key: str) -> Optional[dict]:
        entry = self.entries.get((workflow_id, namespace, key))
        return None if entry is None else {"key": key, "value": entry["value"], "status": entry["status"]}

    async def list(self, workflow_id: str, namespace: str, limit: int) -> list[dict]:
        rows = [
            {"key": key, "value": entry["value"], "status": entry["status"]}
            for (stored_workflow, stored_namespace, key), entry in self.entries.items()
            if stored_workflow == workflow_id and stored_namespace == namespace
        ]
        return rows[:limit]

    async def delete(self, workflow_id: str, namespace: str, key: str) -> bool:
        return self.entries.pop((workflow_id, namespace, key), None) is not None

    async def commit_run(self, run_id: str) -> None:
        for entry in self.entries.values():
            if entry["run_id"] == run_id and entry["status"] == "pending":
                entry["status"] = "committed"

    async def release_run(self, run_id: str) -> None:
        pending = [
            identity
            for identity, entry in self.entries.items()
            if entry["run_id"] == run_id and entry["status"] == "pending"
        ]
        for identity in pending:
            del self.entries[identity]
