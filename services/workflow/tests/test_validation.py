import json
from pathlib import Path

from common.node_specs import BUILTIN_NODE_SPECS, build_custom_spec

from app.schemas import GraphIn
from app.validation import validate_graph

SPECS = dict(BUILTIN_NODE_SPECS)


def graph_of(nodes, edges):
    return GraphIn.model_validate({"nodes": nodes, "edges": edges}).model_dump()


def messages(problems):
    return [entry["message"] for entry in problems]


def test_example_workflow_is_valid():
    path = Path(__file__).resolve().parents[3] / "examples" / "task_assignment_workflow.json"
    graph = graph_of(**json.loads(path.read_text()))
    assert validate_graph(graph, SPECS) == []


def test_requires_exactly_one_trigger_and_connections():
    graph = graph_of(
        [
            {"id": "start", "type": "trigger.manual"},
            {"id": "orphan", "type": "data.static", "config": {"items": [{"a": 1}]}},
        ],
        [],
    )
    found = messages(validate_graph(graph, SPECS))
    assert any("not connected" in text for text in found)


def test_config_schema_enforced():
    graph = graph_of(
        [
            {"id": "start", "type": "trigger.manual"},
            {"id": "mail", "type": "email.send", "config": {"to": "x@y.com"}},
        ],
        [{"source": "start", "target": "mail"}],
    )
    found = messages(validate_graph(graph, SPECS))
    assert any("subject" in text for text in found)


def test_cycle_and_self_loop_detected():
    nodes = [
        {"id": "start", "type": "trigger.manual"},
        {"id": "one", "type": "transform.set", "config": {"fields": {"a": "1"}}},
        {"id": "two", "type": "transform.set", "config": {"fields": {"b": "2"}}},
    ]
    cycle_edges = [
        {"source": "start", "target": "one"},
        {"source": "one", "target": "two"},
        {"source": "two", "target": "one"},
    ]
    cyclic = graph_of(nodes, cycle_edges)
    assert any("cycle" in text for text in messages(validate_graph(cyclic, SPECS)))
    looped = graph_of(nodes, [{"source": "one", "target": "one"}])
    assert any("itself" in text for text in messages(validate_graph(looped, SPECS)))


def test_template_references_must_be_upstream():
    graph = graph_of(
        [
            {"id": "start", "type": "trigger.manual"},
            {"id": "first", "type": "transform.set", "config": {"fields": {"a": "{{nodes.second.items}}"}}},
            {"id": "second", "type": "transform.set", "config": {"fields": {"b": "1"}}},
        ],
        [{"source": "start", "target": "first"}, {"source": "start", "target": "second"}],
    )
    found = messages(validate_graph(graph, SPECS))
    assert any("not upstream" in text for text in found)


def test_unknown_type_and_custom_nodes():
    definition = {
        "key": "ping_service",
        "label": "Ping",
        "parameters": [{"name": "target", "type": "string", "required": True}],
    }
    specs = {**SPECS, "custom.ping_service": build_custom_spec(definition)}
    nodes = [
        {"id": "start", "type": "trigger.manual"},
        {"id": "ping", "type": "custom.ping_service", "config": {}},
        {"id": "ghost", "type": "does.not.exist"},
    ]
    edges = [{"source": "start", "target": "ping"}, {"source": "start", "target": "ghost"}]
    found = messages(validate_graph(graph_of(nodes, edges), specs))
    assert any("target" in text for text in found)
    assert any("Unknown node type" in text for text in found)
