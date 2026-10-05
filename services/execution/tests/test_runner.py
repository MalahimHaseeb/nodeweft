import pytest

from app.engine.errors import NodeExecutionError
from app.memory_store import InMemoryMemoryStore

from tests.helpers import chain, execute, make_context

TASKS = [{"id": 1, "title": "A"}, {"id": 2, "title": "B"}, {"id": 2, "title": "B again"}]


def assignment_graph(extra=None):
    nodes = [
        {"id": "start", "type": "trigger.manual", "config": {}},
        {"id": "tasks", "type": "data.static", "config": {"items": TASKS}},
        {"id": "claim", "type": "memory.claim", "config": {"namespace": "assignments", "key": "task:{{item.id}}"}},
        {
            "id": "remember",
            "type": "memory.set",
            "config": {"namespace": "assignments", "key": "task:{{item.id}}", "value": "dev@x.com"},
        },
    ]
    if extra:
        nodes.append(extra)
    return chain(*nodes)


async def test_claim_dedupes_inside_a_run_and_across_runs():
    memory = InMemoryMemoryStore()
    first = make_context(memory, run_id="run-1")
    logs = await execute(assignment_graph(), first)
    claim_log = next(entry for entry in logs if entry["node_id"] == "claim")
    assert claim_log["items_in"] == 3 and claim_log["items_out"] == 2

    await memory.commit_run("run-1")
    second = make_context(memory, run_id="run-2")
    logs = await execute(assignment_graph(), second)
    claim_log = next(entry for entry in logs if entry["node_id"] == "claim")
    assert claim_log["items_out"] == 0
    stored = await memory.get("wf-1", "assignments", "task:1")
    assert stored["value"] == "dev@x.com" and stored["status"] == "committed"


async def test_failed_run_releases_its_claims():
    memory = InMemoryMemoryStore()
    failing = {"id": "boom", "type": "http.request", "config": {"method": "GET", "url": "http://127.0.0.1:9/"}}
    context = make_context(memory, run_id="run-1")
    with pytest.raises(NodeExecutionError) as caught:
        await execute(assignment_graph(failing), context)
    assert caught.value.node_id == "boom"
    assert "blocked" in caught.value.message
    await memory.release_run("run-1")
    assert memory.entries == {}

    retry = make_context(memory, run_id="run-2")
    logs = await execute(assignment_graph(), retry)
    assert next(entry for entry in logs if entry["node_id"] == "claim")["items_out"] == 2


async def test_continue_on_fail_keeps_workflow_going():
    graph = chain(
        {"id": "start", "type": "trigger.manual", "config": {}},
        {"id": "bad", "type": "http.request", "continue_on_fail": True, "config": {"method": "GET", "url": "http://localhost/"}},
        {"id": "after", "type": "transform.set", "config": {"fields": {"seen": "yes"}}},
    )
    logs = await execute(graph, make_context())
    statuses = {entry["node_id"]: entry["status"] for entry in logs}
    assert statuses["bad"] == "failed" and statuses["after"] == "succeeded"


async def test_trigger_passes_run_input_and_transform_renders_templates():
    graph = chain(
        {"id": "start", "type": "trigger.manual", "config": {}},
        {"id": "label", "type": "transform.set", "config": {"fields": {"label": "{{item.name}} / {{run.workflow_id}}"}}},
    )
    context = make_context(run_input={"items": [{"name": "Ayesha"}, {"name": "Bilal"}]})
    await execute(graph, context)
    assert [item["label"] for item in context.node_outputs["label"]] == ["Ayesha / wf-1", "Bilal / wf-1"]


async def test_filter_operators():
    items = [{"priority": "high", "points": 8}, {"priority": "low", "points": 2}, {"priority": "High", "points": "5"}]
    graph = chain(
        {"id": "start", "type": "trigger.manual", "config": {}},
        {"id": "data", "type": "data.static", "config": {"items": items}},
        {"id": "high", "type": "filter.condition", "config": {"field": "priority", "operator": "eq", "value": "high"}},
        {"id": "big", "type": "filter.condition", "config": {"field": "points", "operator": "gte", "value": 5}},
    )
    context = make_context()
    await execute(graph, context)
    assert [item["points"] for item in context.node_outputs["big"]] == [8, "5"]


async def test_template_error_fails_node_with_clear_message():
    graph = chain(
        {"id": "start", "type": "trigger.manual", "config": {}},
        {"id": "data", "type": "data.static", "config": {"items": [{"a": 1}]}},
        {"id": "bad", "type": "transform.set", "config": {"fields": {"x": "{{item.missing}}"}}},
    )
    with pytest.raises(NodeExecutionError) as caught:
        await execute(graph, make_context())
    assert "missing" in caught.value.message


async def test_email_node_logs_in_dev_and_blocks_disallowed_domain():
    graph = chain(
        {"id": "start", "type": "trigger.manual", "config": {}},
        {"id": "data", "type": "data.static", "config": {"items": [{"to": "a@corp.com", "t": "Hi"}]}},
        {"id": "mail", "type": "email.send", "config": {"to": "{{item.to}}", "subject": "{{item.t}}", "body": "x"}},
    )
    context = make_context(email_allowed_domains="corp.com")
    await execute(graph, context)
    assert context.node_outputs["mail"][0]["email"]["status"] == "logged"

    blocked = make_context(email_allowed_domains="other.com")
    with pytest.raises(NodeExecutionError) as caught:
        await execute(graph, blocked)
    assert "not allowed" in caught.value.message


async def test_email_rejects_header_injection():
    graph = chain(
        {"id": "start", "type": "trigger.manual", "config": {}},
        {"id": "data", "type": "data.static", "config": {"items": [{"to": "a@corp.com\nbcc: evil@x.com"}]}},
        {"id": "mail", "type": "email.send", "config": {"to": "{{item.to}}", "subject": "s", "body": "b"}},
    )
    with pytest.raises(NodeExecutionError):
        await execute(graph, make_context())


async def test_email_cap_per_run():
    items = [{"to": f"u{index}@x.com"} for index in range(3)]
    graph = chain(
        {"id": "start", "type": "trigger.manual", "config": {}},
        {"id": "data", "type": "data.static", "config": {"items": items}},
        {"id": "mail", "type": "email.send", "config": {"to": "{{item.to}}", "subject": "s", "body": "b"}},
    )
    with pytest.raises(NodeExecutionError) as caught:
        await execute(graph, make_context(max_emails_per_run=2))
    assert "limit" in caught.value.message
