from dataclasses import dataclass, field
from typing import Any

from app.memory_store import MemoryStore
from app.settings import ExecutionSettings


@dataclass
class RunContext:
    run_id: str
    workflow_id: str
    owner_id: str
    settings: ExecutionSettings
    memory: MemoryStore
    run_input: dict = field(default_factory=dict)
    custom_nodes: dict = field(default_factory=dict)
    node_outputs: dict[str, list[dict]] = field(default_factory=dict)
    emails_sent: int = 0

    def template_context(self, item: dict | None = None) -> dict[str, Any]:
        context: dict[str, Any] = {
            "nodes": {node_id: {"items": items} for node_id, items in self.node_outputs.items()},
            "run": {"id": self.run_id, "workflow_id": self.workflow_id},
        }
        if item is not None:
            context["item"] = item
        return context
