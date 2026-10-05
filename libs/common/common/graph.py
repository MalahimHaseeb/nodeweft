from collections import deque
from typing import Any


def build_adjacency(nodes: list[dict], edges: list[dict]) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    parents: dict[str, list[str]] = {node["id"]: [] for node in nodes}
    children: dict[str, list[str]] = {node["id"]: [] for node in nodes}
    for edge in edges:
        source, target = edge["source"], edge["target"]
        if source not in parents or target not in parents:
            continue
        if source not in parents[target]:
            parents[target].append(source)
            children[source].append(target)
    return parents, children


def topological_order(nodes: list[dict], edges: list[dict]) -> list[str]:
    parents, children = build_adjacency(nodes, edges)
    pending = {node_id: len(parent_ids) for node_id, parent_ids in parents.items()}
    ready = deque(node_id for node_id, count in pending.items() if count == 0)
    ordered: list[str] = []
    while ready:
        current = ready.popleft()
        ordered.append(current)
        for child in children[current]:
            pending[child] -= 1
            if pending[child] == 0:
                ready.append(child)
    if len(ordered) != len(parents):
        raise ValueError("Workflow contains a cycle")
    return ordered


def ancestors_of(node_id: str, parents: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(parents.get(node_id, []))
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        stack.extend(parents.get(current, []))
    return seen


def find_duplicates(values: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    duplicates: list[Any] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates
