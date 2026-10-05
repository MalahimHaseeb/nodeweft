from common.config import CommonSettings


class WorkflowSettings(CommonSettings):
    mongo_url: str
    mongo_db_name: str = "nodeweft_workflows"
