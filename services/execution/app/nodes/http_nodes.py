from app.engine.context import RunContext
from app.engine.errors import NodeError
from app.nodes.safe_http import safe_request
from app.nodes.util import map_bounded, render_for_item
from app.settings import split_csv


async def http_request(node: dict, items: list[dict], ctx: RunContext) -> list[dict]:
    config = node["config"]
    allowed_hosts = split_csv(ctx.settings.http_allowed_hosts)

    async def call(item: dict) -> dict:
        rendered = render_for_item(
            {"url": config["url"], "headers": config.get("headers", {}), "body": config.get("body")},
            ctx.template_context(item),
        )
        result = await safe_request(
            config["method"],
            rendered["url"],
            rendered["headers"],
            rendered["body"],
            config.get("timeout_seconds", 15),
            allowed_hosts,
        )
        return {**item, "http": result}

    return await map_bounded(call, items, 5)


async def custom_http_node(node: dict, items: list[dict], ctx: RunContext) -> list[dict]:
    key = node["type"].removeprefix("custom.")
    definition = ctx.custom_nodes.get(key)
    if definition is None:
        raise NodeError(f"Custom node '{key}' is not part of this workflow version")
    request = definition["request"]
    allowed_hosts = split_csv(ctx.settings.http_allowed_hosts)

    async def call(item: dict) -> dict:
        context = ctx.template_context(item)
        params = render_for_item(node.get("config", {}), context)
        rendered = render_for_item(
            {"url": request["url"], "headers": request.get("headers", {}), "body": request.get("body")},
            {**context, "params": params},
        )
        result = await safe_request(request["method"], rendered["url"], rendered["headers"], rendered["body"], 15, allowed_hosts)
        return {**item, "result": result}

    return await map_bounded(call, items, 5)
