import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.engine.context import RunContext
from app.engine.errors import NodeExecutionError
from app.engine.runner import GraphRunner
from app.memory_store import MemoryStore
from app.models import Run, RunNodeLog
from app.settings import ExecutionSettings

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RunService:
    def __init__(self, session_factory: async_sessionmaker, memory: MemoryStore, settings: ExecutionSettings):
        self._factory = session_factory
        self._memory = memory
        self._settings = settings

    async def _claim_run(self, run_id: str) -> Run | None:
        async with self._factory() as session:
            result = await session.execute(
                update(Run)
                .where(Run.id == run_id, Run.status == "queued")
                .values(status="running", started_at=utcnow())
                .returning(Run)
            )
            run = result.scalar_one_or_none()
            await session.commit()
            return run

    async def _finish(self, run_id: str, status: str, error: str | None) -> None:
        async with self._factory() as session:
            await session.execute(
                update(Run).where(Run.id == run_id).values(status=status, error=error, finished_at=utcnow())
            )
            await session.commit()

    async def _write_log(self, run_id: str, entry: dict) -> None:
        async with self._factory() as session:
            session.add(RunNodeLog(run_id=run_id, **entry))
            await session.commit()

    async def process(self, run_id: str) -> None:
        run = await self._claim_run(run_id)
        if run is None:
            return

        context = RunContext(
            run_id=run.id,
            workflow_id=run.workflow_id,
            owner_id=run.owner_id,
            settings=self._settings,
            memory=self._memory,
            run_input=run.run_input or {},
            custom_nodes=run.custom_nodes or {},
        )

        async def write_log(entry: dict) -> None:
            await self._write_log(run.id, entry)

        runner = GraphRunner(context, write_log)
        try:
            await asyncio.wait_for(runner.run(run.graph), timeout=self._settings.run_timeout_seconds)
        except NodeExecutionError as error:
            await self._memory.release_run(run.id)
            await self._finish(run.id, "failed", f"Node '{error.node_id}' failed: {error.message}")
        except asyncio.TimeoutError:
            await self._memory.release_run(run.id)
            await self._finish(run.id, "failed", f"Run exceeded {self._settings.run_timeout_seconds} seconds")
        except asyncio.CancelledError:
            await self._memory.release_run(run.id)
            await self._finish(run.id, "cancelled", "Run was cancelled because the worker stopped")
            raise
        except Exception:
            logger.exception("Run %s crashed", run.id)
            await self._memory.release_run(run.id)
            await self._finish(run.id, "failed", "Unexpected error, see service logs")
        else:
            await self._memory.commit_run(run.id)
            await self._finish(run.id, "succeeded", None)

    async def recover(self, enqueue) -> None:
        async with self._factory() as session:
            interrupted = (await session.execute(select(Run.id).where(Run.status == "running"))).scalars().all()
            queued = (await session.execute(select(Run.id).where(Run.status == "queued"))).scalars().all()
        for run_id in interrupted:
            await self._memory.release_run(run_id)
            await self._finish(run_id, "failed", "Run was interrupted by a restart")
        for run_id in queued:
            await enqueue(run_id)
