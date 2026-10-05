from typing import Annotated, Any, Literal, Optional, Union
from uuid import uuid4

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.deps import get_current_user
from common.errors import AppError, NotFoundError
from common.rate_limit import SlidingWindowRateLimiter
from common.responses import success_response
from common.security import AuthUser

from app.models import Run, RunNodeLog
from app.workflow_client import fetch_version, fetch_workflow

router = APIRouter()

run_limiter = SlidingWindowRateLimiter("exec_run", limit=20, window_seconds=60)
read_limiter = SlidingWindowRateLimiter("exec_read", limit=240, window_seconds=60)
memory_limiter = SlidingWindowRateLimiter("exec_memory", limit=60, window_seconds=60)

WorkflowId = Annotated[str, Path(pattern=r"^[A-Za-z0-9\-]{1,64}$")]
RunId = Annotated[str, Path(pattern=r"^[A-Za-z0-9\-]{36}$")]


class RunInput(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)
    data: Optional[dict[str, Any]] = None


class RunCreate(BaseModel):
    workflow_id: str = Field(pattern=r"^[A-Za-z0-9\-]{1,64}$")
    version: Union[int, Literal["latest"]] = "latest"
    input: RunInput = Field(default_factory=RunInput)


async def get_session(request: Request):
    async with request.app.state.session_factory() as session:
        yield session


def serialize_run(run: Run) -> dict:
    return {
        "id": run.id,
        "workflow_id": run.workflow_id,
        "version": run.version,
        "status": run.status,
        "error": run.error,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


async def get_visible_run(session: AsyncSession, run_id: str, user: AuthUser) -> Run:
    run = await session.get(Run, run_id)
    if run is None or (run.owner_id != user.id and not user.is_admin):
        raise NotFoundError("Run")
    return run


async def assert_workflow_access(request: Request, workflow_id: str, user: AuthUser) -> None:
    workflow = await fetch_workflow(request.app.state.http_client, request.app.state.settings, workflow_id)
    if workflow["owner_id"] != user.id and not user.is_admin:
        raise NotFoundError("Workflow")


@router.post("/runs", dependencies=[Depends(get_current_user), Depends(run_limiter)])
async def create_run(
    body: RunCreate,
    request: Request,
    user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    published = await fetch_version(
        request.app.state.http_client, request.app.state.settings, body.workflow_id, str(body.version)
    )
    if published["owner_id"] != user.id and not user.is_admin:
        raise NotFoundError("Workflow")

    run = Run(
        id=str(uuid4()),
        workflow_id=body.workflow_id,
        version=published["version"],
        owner_id=user.id,
        status="queued",
        graph=published["graph"],
        custom_nodes=published.get("custom_nodes", {}),
        run_input=body.input.model_dump(),
    )
    session.add(run)
    await session.commit()

    try:
        await request.app.state.queue.enqueue(run.id)
    except AppError:
        run.status = "failed"
        run.error = "Could not queue the run"
        await session.commit()
        raise
    return success_response({"id": run.id, "status": run.status, "version": run.version}, "Run queued", 202)


@router.get("/runs", dependencies=[Depends(get_current_user), Depends(read_limiter)])
async def list_runs(
    user: AuthUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    workflow_id: Optional[str] = Query(None, pattern=r"^[A-Za-z0-9\-]{1,64}$"),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
):
    statement = select(Run).where(Run.owner_id == user.id)
    if workflow_id:
        statement = statement.where(Run.workflow_id == workflow_id)
    result = await session.execute(statement.order_by(Run.created_at.desc()).limit(limit).offset(offset))
    return success_response([serialize_run(run) for run in result.scalars()])


@router.get("/runs/{run_id}", dependencies=[Depends(get_current_user), Depends(read_limiter)])
async def get_run(run_id: RunId, user: AuthUser = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return success_response(serialize_run(await get_visible_run(session, run_id, user)))


@router.get("/runs/{run_id}/logs", dependencies=[Depends(get_current_user), Depends(read_limiter)])
async def get_run_logs(run_id: RunId, user: AuthUser = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    await get_visible_run(session, run_id, user)
    result = await session.execute(select(RunNodeLog).where(RunNodeLog.run_id == run_id).order_by(RunNodeLog.id))
    logs = [
        {
            "node_id": entry.node_id,
            "node_type": entry.node_type,
            "status": entry.status,
            "items_in": entry.items_in,
            "items_out": entry.items_out,
            "duration_ms": entry.duration_ms,
            "error": entry.error,
            "output_preview": entry.output_preview,
            "created_at": entry.created_at,
        }
        for entry in result.scalars()
    ]
    return success_response(logs)


@router.get("/workflows/{workflow_id}/memory", dependencies=[Depends(get_current_user), Depends(memory_limiter)])
async def list_memory(
    workflow_id: WorkflowId,
    request: Request,
    user: AuthUser = Depends(get_current_user),
    namespace: str = Query("default", min_length=1, max_length=64),
    limit: int = Query(100, ge=1, le=500),
):
    await assert_workflow_access(request, workflow_id, user)
    entries = await request.app.state.memory.list(workflow_id, namespace, limit)
    return success_response(entries)


@router.delete("/workflows/{workflow_id}/memory", dependencies=[Depends(get_current_user), Depends(memory_limiter)])
async def forget_memory(
    workflow_id: WorkflowId,
    request: Request,
    user: AuthUser = Depends(get_current_user),
    namespace: str = Query("default", min_length=1, max_length=64),
    key: str = Query(..., min_length=1, max_length=300),
):
    await assert_workflow_access(request, workflow_id, user)
    removed = await request.app.state.memory.delete(workflow_id, namespace, key)
    if not removed:
        raise NotFoundError("Memory entry")
    return success_response(None, "Memory entry removed")
