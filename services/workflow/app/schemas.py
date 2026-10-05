from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from common.node_specs import FIELD_NAME_PATTERN, HTTP_METHODS, NODE_ID_PATTERN

NodeIdField = Field(pattern=NODE_ID_PATTERN)


class NodeIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = NodeIdField
    type: str = Field(min_length=1, max_length=80)
    name: Optional[str] = Field(default=None, max_length=120)
    position: Optional[dict[str, float]] = None
    config: dict[str, Any] = Field(default_factory=dict)
    continue_on_fail: bool = False


class EdgeIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str = NodeIdField
    target: str = NodeIdField


class GraphIn(BaseModel):
    nodes: list[NodeIn] = Field(default_factory=list, max_length=100)
    edges: list[EdgeIn] = Field(default_factory=list, max_length=400)


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    graph: GraphIn = Field(default_factory=GraphIn)


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=1000)
    graph: Optional[GraphIn] = None


class ParameterIn(BaseModel):
    name: str = Field(pattern=FIELD_NAME_PATTERN)
    type: Literal["string", "number", "boolean"]
    required: bool = False


class HttpRequestDefinition(BaseModel):
    method: Literal[tuple(HTTP_METHODS)]
    url: str = Field(min_length=1, max_length=2000, pattern=r"^(https?://|\{\{)")
    headers: dict[str, str] = Field(default_factory=dict, max_length=20)
    body: Any = None


class CustomNodeCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{2,40}$")
    label: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    parameters: list[ParameterIn] = Field(default_factory=list, max_length=20)
    request: HttpRequestDefinition
