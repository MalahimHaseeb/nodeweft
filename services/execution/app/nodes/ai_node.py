from app.engine.agent import AgentRunner, build_chat_model, build_system_prompt
from app.engine.context import RunContext
from app.engine.errors import NodeError
from app.nodes.agent_tools import build_tools
from app.nodes.util import map_bounded, render_for_item


async def ai_agent(node: dict, items: list[dict], ctx: RunContext) -> list[dict]:
    if not items:
        return []
    config = node["config"]
    if len(items) > ctx.settings.max_ai_items_per_run:
        raise NodeError(f"AI node is limited to {ctx.settings.max_ai_items_per_run} items per run")

    output_fields = config["output_fields"]
    system_prompt = build_system_prompt(config["instructions"], output_fields)
    runner = AgentRunner(
        build_chat_model(ctx.settings),
        build_tools(config.get("tools", []), ctx),
        config.get("max_steps", 4),
    )

    async def process(item: dict) -> dict:
        task_text = render_for_item(config["task"], ctx.template_context(item))
        answer = await runner.run(system_prompt, str(task_text), output_fields)
        return {**item, "ai": answer}

    return await map_bounded(process, items, config.get("concurrency", 2))
