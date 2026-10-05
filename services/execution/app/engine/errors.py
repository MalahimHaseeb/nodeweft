class NodeError(Exception):
    pass


class NodeExecutionError(Exception):
    def __init__(self, node_id: str, message: str):
        super().__init__(message)
        self.node_id = node_id
        self.message = message
