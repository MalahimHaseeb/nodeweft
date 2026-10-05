from jsonschema import Draft202012Validator

from common.graph import ancestors_of, build_adjacency, find_duplicates, topological_order
from common.templating import referenced_node_ids


def problem(node_id: str | None, message: str) -> dict:
    return {"node_id": node_id, "message": message}


def validate_graph(graph: dict, specs: dict[str, dict]) -> list[dict]:
    problems: list[dict] = []
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    if not nodes:
        return [problem(None, "Workflow has no nodes")]

    node_ids = [node["id"] for node in nodes]
    for duplicate in find_duplicates(node_ids):
        problems.append(problem(duplicate, "Node id is used more than once"))
    known_ids = set(node_ids)

    for node in nodes:
        spec = specs.get(node["type"])
        if spec is None:
            problems.append(problem(node["id"], f"Unknown node type '{node['type']}'"))
            continue
        validator = Draft202012Validator(spec["config_schema"])
        for error in validator.iter_errors(node.get("config", {})):
            location = ".".join(str(part) for part in error.absolute_path)
            prefix = f"{location}: " if location else ""
            problems.append(problem(node["id"], f"{prefix}{error.message}"))

    edges_are_valid = True
    for edge in edges:
        if edge["source"] not in known_ids or edge["target"] not in known_ids:
            problems.append(problem(None, f"Edge {edge['source']} to {edge['target']} points to a missing node"))
            edges_are_valid = False
        elif edge["source"] == edge["target"]:
            problems.append(problem(edge["source"], "A node cannot connect to itself"))
            edges_are_valid = False

    trigger_ids = [node["id"] for node in nodes if specs.get(node["type"], {}).get("is_trigger")]
    if len(trigger_ids) != 1:
        problems.append(problem(None, "Workflow needs exactly one trigger node"))

    if not edges_are_valid:
        return problems

    parents, _ = build_adjacency(nodes, edges)
    for node in nodes:
        is_trigger = node["id"] in trigger_ids
        if is_trigger and parents[node["id"]]:
            problems.append(problem(node["id"], "A trigger cannot have incoming connections"))
        if not is_trigger and specs.get(node["type"]) and not parents[node["id"]]:
            problems.append(problem(node["id"], "Node is not connected to anything upstream"))

    try:
        topological_order(nodes, edges)
    except ValueError:
        problems.append(problem(None, "Workflow contains a cycle"))
        return problems

    for node in nodes:
        allowed = ancestors_of(node["id"], parents)
        for referenced in referenced_node_ids(node.get("config", {})):
            if referenced not in known_ids:
                problems.append(problem(node["id"], f"References unknown node '{referenced}'"))
            elif referenced not in allowed:
                problems.append(problem(node["id"], f"References '{referenced}' which is not upstream of this node"))

    return problems
