from app.engine.context import RunContext
from app.engine.errors import NodeError
from app.nodes.util import render_for_item


def resolve_key(raw_key) -> str:
    key = "" if raw_key is None else str(raw_key).strip()
    if not key:
        raise NodeError("Memory key resolved to an empty value")
    if len(key) > 300:
        raise NodeError("Memory key is longer than 300 characters")
    return key


async def memory_claim(node: dict, items: list[dict], ctx: RunContext) -> list[dict]:
    config = node["config"]
    namespace = config.get("namespace", "default")
    claimed = []
    for item in items:
        context = ctx.template_context(item)
        key = resolve_key(render_for_item(config["key"], context))
        value = render_for_item(config.get("value"), context)
        if await ctx.memory.claim(ctx.workflow_id, namespace, key, value, ctx.run_id):
            claimed.append(item)
    return claimed


async def memory_set(node: dict, items: list[dict], ctx: RunContext) -> list[dict]:
    config = node["config"]
    namespace = config.get("namespace", "default")
    for item in items:
        context = ctx.template_context(item)
        key = resolve_key(render_for_item(config["key"], context))
        value = render_for_item(config.get("value"), context)
        await ctx.memory.set(ctx.workflow_id, namespace, key, value, ctx.run_id)
    return items
