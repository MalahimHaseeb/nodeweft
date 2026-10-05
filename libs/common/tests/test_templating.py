import pytest

from common.templating import TemplateError, referenced_node_ids, render_value


CONTEXT = {
    "item": {"id": 7, "title": "Fix login", "ai": {"assignee": "a@x.com"}, "tags": ["a", "b"]},
    "nodes": {"devs": {"items": [{"email": "a@x.com"}]}},
}


def test_whole_placeholder_keeps_type():
    assert render_value("{{item.id}}", CONTEXT) == 7
    assert render_value("{{item.tags}}", CONTEXT) == ["a", "b"]


def test_embedded_placeholder_becomes_text():
    assert render_value("Task {{item.id}}: {{item.title}}", CONTEXT) == "Task 7: Fix login"
    assert render_value("Devs {{nodes.devs.items}}", CONTEXT) == 'Devs [{"email": "a@x.com"}]'


def test_nested_structures_and_lists():
    rendered = render_value({"to": ["{{item.ai.assignee}}"], "n": 3}, CONTEXT)
    assert rendered == {"to": ["a@x.com"], "n": 3}
    assert render_value("{{item.tags.1}}", CONTEXT) == "b"


def test_missing_path_raises():
    with pytest.raises(TemplateError):
        render_value("{{item.missing}}", CONTEXT)
    with pytest.raises(TemplateError):
        render_value("{{item.tags.9}}", CONTEXT)


def test_referenced_node_ids():
    value = {"a": "{{nodes.devs.items}} and {{nodes.tasks.items.0}}", "b": ["{{item.id}}"]}
    assert referenced_node_ids(value) == {"devs", "tasks"}
