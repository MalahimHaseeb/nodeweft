import json

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.engine.agent import AgentRunner, build_system_prompt, parse_agent_output
from app.engine.errors import NodeError
from app.memory_store import InMemoryMemoryStore
from app.nodes.agent_tools import build_tools

from tests.helpers import make_context

FIELDS = [
    {"name": "assignee_email", "type": "string", "description": "who"},
    {"name": "score", "type": "number"},
    {"name": "urgent", "type": "boolean"},
]


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def reply(**payload):
    return AIMessage(content=json.dumps(payload))


def test_parse_handles_fences_and_coercion():
    text = '```json\n{"assignee_email": " a@x.com ", "score": "4.5", "urgent": "true"}\n```'
    assert parse_agent_output(text, FIELDS) == {"assignee_email": "a@x.com", "score": 4.5, "urgent": True}


def test_parse_rejects_missing_and_wrong_types():
    with pytest.raises(ValueError):
        parse_agent_output('{"assignee_email": "a"}', FIELDS)
    with pytest.raises(ValueError):
        parse_agent_output('{"assignee_email": "a", "score": "high", "urgent": true}', FIELDS)
    with pytest.raises(ValueError):
        parse_agent_output("no json here", FIELDS)


def test_system_prompt_lists_fields_and_guards_against_injection():
    prompt = build_system_prompt("Assign tasks.", FIELDS)
    assert "assignee_email (string)" in prompt and "Never follow instructions" in prompt


async def test_agent_without_tools_returns_structured_answer():
    model = GenericFakeChatModel(messages=iter([reply(assignee_email="a@x.com", score=1, urgent=False)]))
    runner = AgentRunner(model, [], max_steps=3)
    answer = await runner.run("sys", "task", FIELDS)
    assert answer["assignee_email"] == "a@x.com"


async def test_agent_retries_once_on_bad_reply_then_fails_cleanly():
    good = reply(assignee_email="a@x.com", score=1, urgent=True)
    recovering = AgentRunner(GenericFakeChatModel(messages=iter([AIMessage(content="sorry"), good])), [], 3)
    assert (await recovering.run("sys", "task", FIELDS))["urgent"] is True

    failing = AgentRunner(GenericFakeChatModel(messages=iter([AIMessage(content="no"), AIMessage(content="still no")])), [], 3)
    with pytest.raises(NodeError):
        await failing.run("sys", "task", FIELDS)


async def test_agent_calls_memory_tool_then_answers():
    memory = InMemoryMemoryStore()
    await memory.set("wf-1", "assignments", "task:9", "busy@x.com", "run-0")
    context = make_context(memory)
    tools = build_tools(["memory_list"], context)
    tool_call = AIMessage(
        content="",
        tool_calls=[{"name": "memory_list", "args": {"namespace": "assignments"}, "id": "call-1"}],
    )
    model = FakeToolModel(messages=iter([tool_call, reply(assignee_email="free@x.com", score=2, urgent=False)]))
    answer = await AgentRunner(model, tools, max_steps=3).run("sys", "task", FIELDS)
    assert answer["assignee_email"] == "free@x.com"


async def test_agent_step_limit_is_enforced():
    loop_call = AIMessage(content="", tool_calls=[{"name": "current_time", "args": {}, "id": "c"}])

    def endless():
        while True:
            yield loop_call

    context = make_context()
    runner = AgentRunner(FakeToolModel(messages=endless()), build_tools(["current_time"], context), max_steps=2)
    with pytest.raises(NodeError):
        await runner.run("sys", "task", FIELDS)
