import json
from datetime import datetime, timezone

from langchain_core.tools import BaseTool, StructuredTool

from app.engine.context import RunContext

MAX_TOOL_OUTPUT_CHARS = 8000
MAX_TOOL_ENTRIES = 200


def build_tools(names: list[str], ctx: RunContext) -> list[BaseTool]:
    async def current_time() -> str:
        return datetime.now(timezone.utc).isoformat()

    async def memory_get(key: str, namespace: str = "default") -> str:
        entry = await ctx.memory.get(ctx.workflow_id, namespace[:64], key[:300])
        return json.dumps(entry, default=str) if entry else "null"

    async def memory_list(namespace: str = "default") -> str:
        entries = await ctx.memory.list(ctx.workflow_id, namespace[:64], MAX_TOOL_ENTRIES)
        return json.dumps(entries, default=str)[:MAX_TOOL_OUTPUT_CHARS]

    catalog = {
        "current_time": StructuredTool.from_function(
            coroutine=current_time,
            name="current_time",
            description="Returns the current UTC date and time in ISO format.",
        ),
        "memory_get": StructuredTool.from_function(
            coroutine=memory_get,
            name="memory_get",
            description="Looks up one remembered entry of this workflow by key and namespace.",
        ),
        "memory_list": StructuredTool.from_function(
            coroutine=memory_list,
            name="memory_list",
            description="Lists remembered entries of this workflow in a namespace, for example existing task assignments.",
        ),
    }
    return [catalog[name] for name in names if name in catalog]
