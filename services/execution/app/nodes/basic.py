from typing import Any

from app.engine.context import RunContext
from app.nodes.util import get_field, render_for_item


async def trigger_manual(node: dict, items: list[dict], ctx: RunContext) -> list[dict]:
    provided = ctx.run_input.get("items")
    if isinstance(provided, list) and provided:
        return [entry for entry in provided if isinstance(entry, dict)]
    data = ctx.run_input.get("data")
    if isinstance(data, dict):
        return [data]
    return [{}]


async def data_static(node: dict, items: list[dict], ctx: RunContext) -> list[dict]:
    return [dict(entry) for entry in node["config"]["items"]]


def to_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def compare(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "exists":
        return actual is not None and actual != ""
    if operator == "not_exists":
        return actual is None or actual == ""
    if operator == "eq":
        return str(actual).strip().lower() == str(expected).strip().lower()
    if operator == "ne":
        return str(actual).strip().lower() != str(expected).strip().lower()
    if operator == "contains":
        if actual is None:
            return False
        return str(expected).lower() in str(actual).lower()
    if operator == "in":
        options = expected if isinstance(expected, list) else [part.strip() for part in str(expected).split(",")]
        return str(actual).strip().lower() in {str(option).strip().lower() for option in options}
    left, right = to_number(actual), to_number(expected)
    if left is None or right is None:
        return False
    return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}[operator]


async def filter_condition(node: dict, items: list[dict], ctx: RunContext) -> list[dict]:
    config = node["config"]
    kept = []
    for item in items:
        expected = render_for_item(config.get("value"), ctx.template_context(item))
        _, actual = get_field(item, config["field"])
        if compare(config["operator"], actual, expected):
            kept.append(item)
    return kept


async def transform_set(node: dict, items: list[dict], ctx: RunContext) -> list[dict]:
    fields = node["config"]["fields"]
    results = []
    for item in items:
        context = ctx.template_context(item)
        updated = dict(item)
        for name, template in fields.items():
            updated[name] = render_for_item(template, context)
        results.append(updated)
    return results
