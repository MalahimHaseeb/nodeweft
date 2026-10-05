from app.engine.context import RunContext
from app.engine.runner import GraphRunner
from app.memory_store import InMemoryMemoryStore
from app.settings import ExecutionSettings


def make_context(memory=None, run_id="run-1", run_input=None, **settings_overrides):
    settings = ExecutionSettings(**settings_overrides)
    return RunContext(
        run_id=run_id,
        workflow_id="wf-1",
        owner_id="user-1",
        settings=settings,
        memory=memory or InMemoryMemoryStore(),
        run_input=run_input or {},
    )


async def execute(graph, context):
    logs = []

    async def collect(entry):
        logs.append(entry)

    await GraphRunner(context, collect).run(graph)
    return logs


def chain(*nodes):
    edges = [{"source": nodes[index]["id"], "target": nodes[index + 1]["id"]} for index in range(len(nodes) - 1)]
    return {"nodes": list(nodes), "edges": edges}
