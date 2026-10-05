import json
import re
from typing import Any

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)\s*\}\}")


class TemplateError(ValueError):
    pass


def resolve_path(path: str, context: dict) -> Any:
    current: Any = context
    for segment in path.split("."):
        if isinstance(current, dict):
            if segment not in current:
                raise TemplateError(f"'{path}' was not found")
            current = current[segment]
        elif isinstance(current, list):
            if not segment.isdigit() or int(segment) >= len(current):
                raise TemplateError(f"'{path}' was not found")
            current = current[int(segment)]
        else:
            raise TemplateError(f"'{path}' was not found")
    return current


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def render_string(template: str, context: dict) -> Any:
    whole = PLACEHOLDER.fullmatch(template.strip())
    if whole:
        return resolve_path(whole.group(1), context)
    return PLACEHOLDER.sub(lambda match: stringify(resolve_path(match.group(1), context)), template)


def render_value(value: Any, context: dict) -> Any:
    if isinstance(value, str):
        return render_string(value, context)
    if isinstance(value, list):
        return [render_value(entry, context) for entry in value]
    if isinstance(value, dict):
        return {key: render_value(entry, context) for key, entry in value.items()}
    return value


def find_references(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found.update(match.group(1) for match in PLACEHOLDER.finditer(value))
    elif isinstance(value, list):
        for entry in value:
            found.update(find_references(entry))
    elif isinstance(value, dict):
        for entry in value.values():
            found.update(find_references(entry))
    return found


def referenced_node_ids(value: Any) -> set[str]:
    node_ids: set[str] = set()
    for path in find_references(value):
        parts = path.split(".")
        if len(parts) >= 2 and parts[0] == "nodes":
            node_ids.add(parts[1])
    return node_ids
