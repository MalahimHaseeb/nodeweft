import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

from common.graph import build_adjacency, topological_order
from common.templating import TemplateError

from app.engine.context import RunContext
from app.engine.errors import NodeError, NodeExecutionError
from app.nodes import resolve_executor

logger = logging.getLogger(__name__)

NodeLogWriter = Callable[[dict], Awaitable[None]]

PREVIEW_ITEMS = 5
PREVIEW_MAX_CHARS = 20000


def normalise_output(items, limit: int) -> list[dict]:
    if not isinstance(items, list):
        raise NodeError("Node returned an invalid result")
    if len(items) > limit:
        raise NodeError(f"Node produced more than {limit} items")
    if any(not isinstance(item, dict) for item in items):
        raise NodeError("Node returned items that are not objects")
    try:
        json.dumps(items)
    except (TypeError, ValueError):
        raise NodeError("Node output is not JSON serializable") from None
    return items


def build_preview(items: list[dict]) -> list[dict]:
    preview = items[:PREVIEW_ITEMS]
    if len(json.dumps(preview, default=str)) > PREVIEW_MAX_CHARS:
        return [{"keys": sorted(item.keys())} for item in preview]
    return preview


def describe_failure(error: BaseException, node_timeout: int) -> str:
    if isinstance(error, (NodeError, TemplateError)):
        return str(error)
    if isinstance(error, asyncio.TimeoutError):
        return f"Node timed out after {node_timeout} seconds"
    return "Unexpected error in node, see service logs"


class GraphRunner:
    def __init__(self, context: RunContext, write_log: NodeLogWriter):
        self._context = context
        self._write_log = write_log

    async def run(self, graph: dict) -> None:
        nodes = graph["nodes"]
        edges = graph["edges"]
        node_by_id = {node["id"]: node for node in nodes}
        parents, _ = build_adjacency(nodes, edges)
        for node_id in topological_order(nodes, edges):
            incoming = [
                item
                for parent_id in parents[node_id]
                for item in self._context.node_outputs.get(parent_id, [])
            ]
            await self._run_node(node_by_id[node_id], incoming)

    async def _run_node(self, node: dict, incoming: list[dict]) -> None:
        settings = self._context.settings
        started = time.monotonic()
        try:
            executor = resolve_executor(node["type"])
            produced = await asyncio.wait_for(
                executor(node, incoming, self._context),
                timeout=settings.node_timeout_seconds,
            )
            produced = normalise_output(produced, settings.max_items_per_node)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not isinstance(error, (NodeError, TemplateError, asyncio.TimeoutError)):
                logger.exception("Node %s (%s) crashed", node["id"], node["type"])
            message = describe_failure(error, settings.node_timeout_seconds)
            await self._write_log(
                {
                    "node_id": node["id"],
                    "node_type": node["type"],
                    "status": "failed",
                    "items_in": len(incoming),
                    "items_out": 0,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                    "error": message,
                    "output_preview": None,
                }
            )
            if node.get("continue_on_fail"):
                self._context.node_outputs[node["id"]] = []
                return
            raise NodeExecutionError(node["id"], message) from error

        self._context.node_outputs[node["id"]] = produced
        await self._write_log(
            {
                "node_id": node["id"],
                "node_type": node["type"],
                "status": "succeeded",
                "items_in": len(incoming),
                "items_out": len(produced),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "error": None,
                "output_preview": build_preview(produced),
            }
        )
