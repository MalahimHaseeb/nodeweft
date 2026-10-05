from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient

from common.app import create_service_app

from app.routes import router
from app.settings import WorkflowSettings

settings = WorkflowSettings()


async def on_startup(app: FastAPI) -> None:
    client = AsyncIOMotorClient(settings.mongo_url, serverSelectionTimeoutMS=5000)
    db = client[settings.mongo_db_name]
    await db.workflows.create_index("owner_id")
    await db.workflow_versions.create_index([("workflow_id", 1), ("version", -1)], unique=True)
    await db.custom_nodes.create_index("key", unique=True)
    app.state.mongo_client = client
    app.state.db = db


async def on_shutdown(app: FastAPI) -> None:
    app.state.mongo_client.close()


app = create_service_app("Nodeweft Workflow Service", settings, on_startup, on_shutdown)
app.include_router(router)
