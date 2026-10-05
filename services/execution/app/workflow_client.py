import httpx

from common.errors import NotFoundError, ServiceUnavailableError

from app.settings import ExecutionSettings


async def fetch_from_workflow_service(client: httpx.AsyncClient, settings: ExecutionSettings, path: str) -> dict:
    try:
        response = await client.get(
            f"{settings.workflow_service_url}{path}",
            headers={"X-Internal-Token": settings.internal_service_token},
            timeout=5,
        )
    except httpx.HTTPError:
        raise ServiceUnavailableError("The workflow service is unreachable") from None
    if response.status_code == 404:
        raise NotFoundError("Workflow")
    if response.status_code != 200:
        raise ServiceUnavailableError("The workflow service returned an unexpected response")
    return response.json()["data"]


async def fetch_version(client: httpx.AsyncClient, settings: ExecutionSettings, workflow_id: str, version: str) -> dict:
    return await fetch_from_workflow_service(client, settings, f"/internal/workflows/{workflow_id}/versions/{version}")


async def fetch_workflow(client: httpx.AsyncClient, settings: ExecutionSettings, workflow_id: str) -> dict:
    return await fetch_from_workflow_service(client, settings, f"/internal/workflows/{workflow_id}")
