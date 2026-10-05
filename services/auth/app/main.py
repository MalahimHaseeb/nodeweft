from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from common.app import create_service_app

from app.mailer import EmailSender
from app.models import Base
from app.otp import OtpService
from app.routes import router
from app.settings import AuthSettings

settings = AuthSettings()


async def on_startup(app: FastAPI) -> None:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=5)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    app.state.engine = engine
    app.state.session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app.state.otp = OtpService(app.state.redis, settings)
    app.state.mailer = EmailSender(settings)


async def on_shutdown(app: FastAPI) -> None:
    await app.state.engine.dispose()


app = create_service_app("Nodeweft Auth Service", settings, on_startup, on_shutdown)
app.include_router(router)
