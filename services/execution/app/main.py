import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.app import create_service_app

from app.memory_store import PostgresMemoryStore
from app.models import Base
from app.queueing import build_queue
from app.routes import router
from app.service import RunService
from app.settings import ExecutionSettings

settings = ExecutionSettings()


async def on_startup(app: FastAPI) -> None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=5)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    memory = PostgresMemoryStore(session_factory, settings.claim_stale_minutes)
    service = RunService(session_factory, memory, settings)
    queue = build_queue(settings, service.process)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.memory = memory
    app.state.queue = queue
    app.state.http_client = httpx.AsyncClient()

    await queue.start()
    if settings.run_queue_backend == "local":
        await service.recover(queue.enqueue)


async def on_shutdown(app: FastAPI) -> None:
    await app.state.queue.stop()
    await app.state.http_client.aclose()
    await app.state.engine.dispose()


app = create_service_app("Nodeweft Execution Service", settings, on_startup, on_shutdown)
app.include_router(router)
