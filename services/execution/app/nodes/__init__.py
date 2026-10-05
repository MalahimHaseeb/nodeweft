from app.engine.errors import NodeError
from app.nodes.ai_node import ai_agent
from app.nodes.basic import data_static, filter_condition, transform_set, trigger_manual
from app.nodes.email_node import email_send
from app.nodes.excel import excel_read
from app.nodes.http_nodes import custom_http_node, http_request
from app.nodes.memory_nodes import memory_claim, memory_set

NODE_EXECUTORS = {
    "trigger.manual": trigger_manual,
    "data.static": data_static,
    "excel.read": excel_read,
    "filter.condition": filter_condition,
    "transform.set": transform_set,
    "memory.claim": memory_claim,
    "memory.set": memory_set,
    "http.request": http_request,
    "email.send": email_send,
    "ai.agent": ai_agent,
}


def resolve_executor(node_type: str):
    if node_type.startswith("custom."):
        return custom_http_node
    executor = NODE_EXECUTORS.get(node_type)
    if executor is None:
        raise NodeError(f"Unknown node type '{node_type}'")
    return executor
