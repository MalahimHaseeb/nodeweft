from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Path, Query, Request
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from common.deps import get_current_user, require_admin, require_internal_token
from common.errors import ConflictError, NotFoundError, UnprocessableError
from common.node_specs import BUILTIN_NODE_SPECS, build_custom_spec
from common.rate_limit import SlidingWindowRateLimiter
from common.responses import success_response
from common.security import AuthUser

from app.schemas import CustomNodeCreate, WorkflowCreate, WorkflowUpdate
from app.validation import validate_graph

router = APIRouter()

read_limiter = SlidingWindowRateLimiter("wf_read", limit=240, window_seconds=60)
write_limiter = SlidingWindowRateLimiter("wf_write", limit=60, window_seconds=60)

WorkflowId = Annotated[str, Path(pattern=r"^[A-Za-z0-9\-]{1,64}$")]
NodeKey = Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]{2,40}$")]


def now() -> datetime:
    return datetime.now(timezone.utc)


def public_document(document: dict) -> dict:
    result = {key: value for key, value in document.items() if key != "_id"}
    result["id"] = document["_id"]
    return result


async def load_specs(db) -> dict[str, dict]:
    specs = dict(BUILTIN_NODE_SPECS)
    async for definition in db.custom_nodes.find({}):
        specs[f"custom.{definition['key']}"] = build_custom_spec(definition)
    return specs


async def get_owned_workflow(db, workflow_id: str, user: AuthUser) -> dict:
    document = await db.workflows.find_one({"_id": workflow_id})
    if document is None or (document["owner_id"] != user.id and not user.is_admin):
        raise NotFoundError("Workflow")
    return document


@router.get("/nodes", dependencies=[Depends(get_current_user), Depends(read_limiter)])
async def list_nodes(request: Request):
    specs = await load_specs(request.app.state.db)
    return success_response(sorted(specs.values(), key=lambda spec: (spec["category"], spec["label"])))


@router.post("/nodes/custom", status_code=201, dependencies=[Depends(require_admin), Depends(write_limiter)])
async def create_custom_node(body: CustomNodeCreate, request: Request, user: AuthUser = Depends(require_admin)):
    document = {
        "_id": str(uuid4()),
        **body.model_dump(),
        "created_by": user.id,
        "created_at": now(),
    }
    try:
        await request.app.state.db.custom_nodes.insert_one(document)
    except DuplicateKeyError:
        raise ConflictError(f"A custom node with key '{body.key}' already exists") from None
    return success_response(build_custom_spec(document), "Custom node created", 201)


@router.delete("/nodes/custom/{key}", dependencies=[Depends(require_admin), Depends(write_limiter)])
async def delete_custom_node(key: NodeKey, request: Request):
    result = await request.app.state.db.custom_nodes.delete_one({"key": key})
    if result.deleted_count == 0:
        raise NotFoundError("Custom node")
    return success_response(None, "Custom node deleted")


@router.post("/workflows", status_code=201, dependencies=[Depends(get_current_user), Depends(write_limiter)])
async def create_workflow(body: WorkflowCreate, request: Request, user: AuthUser = Depends(get_current_user)):
    timestamp = now()
    document = {
        "_id": str(uuid4()),
        "owner_id": user.id,
        "name": body.name,
        "description": body.description,
        "draft": body.graph.model_dump(),
        "latest_version": 0,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    await request.app.state.db.workflows.insert_one(document)
    return success_response(public_document(document), "Workflow created", 201)


@router.get("/workflows", dependencies=[Depends(get_current_user), Depends(read_limiter)])
async def list_workflows(
    request: Request,
    user: AuthUser = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=100),
    skip: int = Query(0, ge=0, le=10000),
):
    cursor = (
        request.app.state.db.workflows.find({"owner_id": user.id}, {"draft": 0})
        .sort("updated_at", -1)
        .skip(skip)
        .limit(limit)
    )
    return success_response([public_document(document) async for document in cursor])


@router.get("/workflows/{workflow_id}", dependencies=[Depends(get_current_user), Depends(read_limiter)])
async def get_workflow(workflow_id: WorkflowId, request: Request, user: AuthUser = Depends(get_current_user)):
    document = await get_owned_workflow(request.app.state.db, workflow_id, user)
    return success_response(public_document(document))


@router.put("/workflows/{workflow_id}", dependencies=[Depends(get_current_user), Depends(write_limiter)])
async def update_workflow(
    workflow_id: WorkflowId,
    body: WorkflowUpdate,
    request: Request,
    user: AuthUser = Depends(get_current_user),
):
    db = request.app.state.db
    await get_owned_workflow(db, workflow_id, user)
    changes: dict = {"updated_at": now()}
    if body.name is not None:
        changes["name"] = body.name
    if body.description is not None:
        changes["description"] = body.description
    if body.graph is not None:
        changes["draft"] = body.graph.model_dump()
    updated = await db.workflows.find_one_and_update(
        {"_id": workflow_id}, {"$set": changes}, return_document=ReturnDocument.AFTER
    )
    if updated is None:
        raise NotFoundError("Workflow")
    return success_response(public_document(updated), "Workflow saved")


@router.delete("/workflows/{workflow_id}", dependencies=[Depends(get_current_user), Depends(write_limiter)])
async def delete_workflow(workflow_id: WorkflowId, request: Request, user: AuthUser = Depends(get_current_user)):
    db = request.app.state.db
    await get_owned_workflow(db, workflow_id, user)
    await db.workflow_versions.delete_many({"workflow_id": workflow_id})
    await db.workflows.delete_one({"_id": workflow_id})
    return success_response(None, "Workflow deleted")


@router.post("/workflows/{workflow_id}/publish", dependencies=[Depends(get_current_user), Depends(write_limiter)])
async def publish_workflow(workflow_id: WorkflowId, request: Request, user: AuthUser = Depends(get_current_user)):
    db = request.app.state.db
    workflow = await get_owned_workflow(db, workflow_id, user)
    graph = workflow["draft"]

    specs = await load_specs(db)
    problems = validate_graph(graph, specs)
    if problems:
        raise UnprocessableError("Workflow is not valid", problems)

    custom_keys = {node["type"].removeprefix("custom.") for node in graph["nodes"] if node["type"].startswith("custom.")}
    custom_nodes = {}
    async for definition in db.custom_nodes.find({"key": {"$in": list(custom_keys)}}):
        custom_nodes[definition["key"]] = {
            "label": definition["label"],
            "parameters": definition["parameters"],
            "request": definition["request"],
        }

    bumped = await db.workflows.find_one_and_update(
        {"_id": workflow_id},
        {"$inc": {"latest_version": 1}, "$set": {"updated_at": now()}},
        return_document=ReturnDocument.AFTER,
    )
    version = bumped["latest_version"]
    await db.workflow_versions.insert_one(
        {
            "_id": str(uuid4()),
            "workflow_id": workflow_id,
            "version": version,
            "owner_id": workflow["owner_id"],
            "name": workflow["name"],
            "graph": graph,
            "custom_nodes": custom_nodes,
            "published_by": user.id,
            "published_at": now(),
        }
    )
    return success_response({"workflow_id": workflow_id, "version": version}, "Workflow published", 201)


@router.get("/workflows/{workflow_id}/versions", dependencies=[Depends(get_current_user), Depends(read_limiter)])
async def list_versions(workflow_id: WorkflowId, request: Request, user: AuthUser = Depends(get_current_user)):
    db = request.app.state.db
    await get_owned_workflow(db, workflow_id, user)
    cursor = (
        db.workflow_versions.find({"workflow_id": workflow_id}, {"graph": 0, "custom_nodes": 0})
        .sort("version", -1)
        .limit(100)
    )
    return success_response([public_document(document) async for document in cursor])


@router.get("/internal/workflows/{workflow_id}", dependencies=[Depends(require_internal_token)])
async def internal_workflow(workflow_id: WorkflowId, request: Request):
    document = await request.app.state.db.workflows.find_one(
        {"_id": workflow_id}, {"owner_id": 1, "latest_version": 1, "name": 1}
    )
    if document is None:
        raise NotFoundError("Workflow")
    return success_response(public_document(document))


@router.get("/internal/workflows/{workflow_id}/versions/{version}", dependencies=[Depends(require_internal_token)])
async def internal_version(
    workflow_id: WorkflowId,
    version: Annotated[str, Path(pattern=r"^(latest|\d{1,9})$")],
    request: Request,
):
    db = request.app.state.db
    if version == "latest":
        workflow = await db.workflows.find_one({"_id": workflow_id}, {"latest_version": 1})
        if workflow is None or workflow["latest_version"] < 1:
            raise NotFoundError("Published version")
        version_number = workflow["latest_version"]
    else:
        version_number = int(version)
    document = await db.workflow_versions.find_one({"workflow_id": workflow_id, "version": version_number})
    if document is None:
        raise NotFoundError("Published version")
    return success_response(public_document(document))
