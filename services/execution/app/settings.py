from pydantic import model_validator

from common.config import CommonSettings


def split_csv(value: str) -> list[str]:
    return [entry.strip().lower() for entry in value.split(",") if entry.strip()]


class ExecutionSettings(CommonSettings):
    database_url: str
    workflow_service_url: str = "http://localhost:8002"
    run_queue_backend: str = "production"
    sqs_queue_url: str = ""
    aws_region: str = "us-east-1"
    local_worker_count: int = 2
    run_timeout_seconds: int = 900
    node_timeout_seconds: int = 120
    max_items_per_node: int = 5000
    max_ai_items_per_run: int = 200
    max_emails_per_run: int = 200
    claim_stale_minutes: int = 30
    s3_bucket: str = ""
    allow_local_files: bool = False
    local_files_dir: str = "/data/files"
    max_file_bytes: int = 10_000_000
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    email_allowed_domains: str = ""
    http_allowed_hosts: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""
    openai_model: str = ""

    @model_validator(mode="after")
    def require_email_allowlist_in_production(self):
        if self.is_production and self.smtp_host and not split_csv(self.email_allowed_domains):
            raise ValueError("email_allowed_domains must be set in production when SMTP is configured")
        return self
