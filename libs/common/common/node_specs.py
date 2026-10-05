from typing import Any

FIELD_NAME_PATTERN = "^[A-Za-z_][A-Za-z0-9_]{0,63}$"
NODE_ID_PATTERN = "^[A-Za-z][A-Za-z0-9_]{0,63}$"
FILTER_OPERATORS = ["eq", "ne", "gt", "gte", "lt", "lte", "contains", "in", "exists", "not_exists"]
AGENT_TOOL_NAMES = ["current_time", "memory_get", "memory_list"]
HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]


def object_schema(properties: dict, required: tuple = ()) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def make_spec(node_type: str, label: str, category: str, description: str, schema: dict, is_trigger: bool = False) -> dict:
    return {
        "type": node_type,
        "label": label,
        "category": category,
        "description": description,
        "is_trigger": is_trigger,
        "config_schema": schema,
    }


MEMORY_PROPERTIES = {
    "namespace": {"type": "string", "minLength": 1, "maxLength": 64, "default": "default"},
    "key": {"type": "string", "minLength": 1, "maxLength": 300},
    "value": {},
}

_SPEC_LIST = [
    make_spec(
        "trigger.manual",
        "Manual trigger",
        "trigger",
        "Starts the workflow when someone runs it. Passes the run input downstream.",
        object_schema({}),
        is_trigger=True,
    ),
    make_spec(
        "data.static",
        "Static data",
        "data",
        "Outputs a fixed list of items, for example a list of developers.",
        object_schema(
            {"items": {"type": "array", "minItems": 1, "maxItems": 1000, "items": {"type": "object"}}},
            ("items",),
        ),
    ),
    make_spec(
        "excel.read",
        "Read Excel or CSV",
        "data",
        "Reads rows from an .xlsx or .csv file in S3 or the local files folder. One row becomes one item.",
        object_schema(
            {
                "source": {"type": "string", "enum": ["local", "s3"]},
                "path": {"type": "string", "minLength": 1, "maxLength": 500},
                "sheet": {"type": "string", "maxLength": 100},
                "max_rows": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 5000},
            },
            ("source", "path"),
        ),
    ),
    make_spec(
        "filter.condition",
        "Filter",
        "logic",
        "Keeps only the items that match a condition.",
        object_schema(
            {
                "field": {"type": "string", "minLength": 1, "maxLength": 200},
                "operator": {"type": "string", "enum": FILTER_OPERATORS},
                "value": {},
            },
            ("field", "operator"),
        ),
    ),
    make_spec(
        "transform.set",
        "Set fields",
        "logic",
        "Adds or overwrites fields on every item using templates.",
        object_schema(
            {
                "fields": {
                    "type": "object",
                    "propertyNames": {"pattern": FIELD_NAME_PATTERN},
                    "minProperties": 1,
                    "maxProperties": 50,
                }
            },
            ("fields",),
        ),
    ),
    make_spec(
        "memory.claim",
        "Claim in memory",
        "memory",
        "Keeps only items whose key has not been claimed before. Claims are released if the run fails.",
        object_schema(MEMORY_PROPERTIES, ("key",)),
    ),
    make_spec(
        "memory.set",
        "Save to memory",
        "memory",
        "Stores a value under a key so later runs remember it.",
        object_schema(MEMORY_PROPERTIES, ("key",)),
    ),
    make_spec(
        "http.request",
        "HTTP request",
        "integration",
        "Calls an external HTTP endpoint once per item. Private network addresses are blocked.",
        object_schema(
            {
                "method": {"type": "string", "enum": HTTP_METHODS},
                "url": {"type": "string", "minLength": 1, "maxLength": 2000},
                "headers": {"type": "object", "maxProperties": 20, "additionalProperties": {"type": "string"}},
                "body": {},
                "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 30, "default": 15},
            },
            ("method", "url"),
        ),
    ),
    make_spec(
        "email.send",
        "Send email",
        "integration",
        "Sends one email per item.",
        object_schema(
            {
                "to": {"type": "string", "minLength": 1, "maxLength": 320},
                "subject": {"type": "string", "minLength": 1, "maxLength": 300},
                "body": {"type": "string", "minLength": 1, "maxLength": 20000},
                "allowed_domains": {"type": "array", "maxItems": 20, "items": {"type": "string", "maxLength": 100}},
            },
            ("to", "subject", "body"),
        ),
    ),
    make_spec(
        "ai.agent",
        "AI agent",
        "ai",
        "Runs an LLM agent for each item. It can call approved tools and must return the declared fields.",
        object_schema(
            {
                "instructions": {"type": "string", "minLength": 1, "maxLength": 4000},
                "task": {"type": "string", "minLength": 1, "maxLength": 8000},
                "output_fields": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 20,
                    "items": object_schema(
                        {
                            "name": {"type": "string", "pattern": FIELD_NAME_PATTERN},
                            "type": {"type": "string", "enum": ["string", "number", "boolean"]},
                            "description": {"type": "string", "maxLength": 300},
                        },
                        ("name", "type"),
                    ),
                },
                "tools": {
                    "type": "array",
                    "uniqueItems": True,
                    "maxItems": 5,
                    "items": {"type": "string", "enum": AGENT_TOOL_NAMES},
                },
                "max_steps": {"type": "integer", "minimum": 1, "maximum": 8, "default": 4},
                "concurrency": {"type": "integer", "minimum": 1, "maximum": 5, "default": 2},
            },
            ("instructions", "task", "output_fields"),
        ),
    ),
]

BUILTIN_NODE_SPECS: dict[str, dict] = {spec["type"]: spec for spec in _SPEC_LIST}


def schema_from_parameters(parameters: list[dict]) -> dict:
    type_map: dict[str, Any] = {
        "string": {"type": "string", "maxLength": 2000},
        "number": {"type": ["number", "string"]},
        "boolean": {"type": ["boolean", "string"]},
    }
    properties = {parameter["name"]: type_map[parameter["type"]] for parameter in parameters}
    required = tuple(parameter["name"] for parameter in parameters if parameter.get("required"))
    return object_schema(properties, required)


def build_custom_spec(definition: dict) -> dict:
    return make_spec(
        f"custom.{definition['key']}",
        definition["label"],
        "custom",
        definition.get("description", ""),
        schema_from_parameters(definition.get("parameters", [])),
    )
