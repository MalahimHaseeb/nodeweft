import sys
from pathlib import Path
from urllib.parse import urlsplit

REQUIRED_KEYS = {
    "auth.env": [
        "APP_ENV", "JWT_SECRET", "INTERNAL_SERVICE_TOKEN", "OTP_SECRET", "ADMIN_EMAILS",
        "REDIS_URL", "DATABASE_URL",
    ],
    "workflow.env": [
        "APP_ENV", "JWT_SECRET", "INTERNAL_SERVICE_TOKEN", "REDIS_URL", "MONGO_URL", "MONGO_DB_NAME",
    ],
    "execution.env": [
        "APP_ENV", "JWT_SECRET", "INTERNAL_SERVICE_TOKEN", "REDIS_URL", "DATABASE_URL",
        "WORKFLOW_SERVICE_URL", "RUN_QUEUE_BACKEND", "SQS_QUEUE_URL", "AWS_REGION",
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "S3_BUCKET",
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
    ],
}

PLACEHOLDER_MARKERS = ["PASSWORD", "XXXX", "<", ">", "yourname", "REGION", "xxxxx", "MODEL_ID", "YOUR_"]

problems: list[str] = []
notes: list[str] = []


def fail(file_name: str, key: str, message: str) -> None:
    problems.append(f"PROBLEM  {file_name}  {key}  {message}")


def parse_env_file(path: Path, file_name: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            fail(file_name, f"line {line_number}", "is not in KEY=VALUE form")
            continue
        key, value = line.split("=", 1)
        if key != key.strip() or key.endswith(" "):
            fail(file_name, key.strip(), "has a space before the equals sign")
        if value.startswith(" "):
            fail(file_name, key.strip(), "has a space after the equals sign")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def has_placeholder(value: str) -> bool:
    return any(marker in value for marker in PLACEHOLDER_MARKERS)


def check_required(file_name: str, values: dict[str, str]) -> None:
    for key in REQUIRED_KEYS[file_name]:
        if not values.get(key):
            fail(file_name, key, "is missing or empty")
        elif key not in ("ADMIN_EMAILS", "APP_ENV", "AWS_REGION") and has_placeholder(values[key]):
            fail(file_name, key, "still looks like a placeholder")


def check_secret_strength(file_name: str, values: dict[str, str]) -> None:
    for key in ("JWT_SECRET", "INTERNAL_SERVICE_TOKEN", "OTP_SECRET"):
        if key in values and values[key] and len(values[key]) < 32:
            fail(file_name, key, "is shorter than 32 characters")


def check_postgres(file_name: str, values: dict[str, str], database_name: str) -> None:
    url = values.get("DATABASE_URL", "")
    if not url:
        return
    if not url.startswith("postgresql+asyncpg://"):
        fail(file_name, "DATABASE_URL", "must start with postgresql+asyncpg://")
    if "sslmode" in url or "channel_binding" in url:
        fail(file_name, "DATABASE_URL", "uses sslmode or channel_binding, use ?ssl=require instead")
    if "ssl=require" not in url:
        fail(file_name, "DATABASE_URL", "is missing ssl=require")
    if "-pooler" in url:
        fail(file_name, "DATABASE_URL", "uses the pooled host, use the direct host without -pooler")
    path = urlsplit(url.replace("postgresql+asyncpg", "postgresql", 1)).path.strip("/")
    if path != database_name:
        fail(file_name, "DATABASE_URL", f"should end in database {database_name}, found {path or 'nothing'}")


def check_mongo(values: dict[str, str]) -> None:
    url = values.get("MONGO_URL", "")
    if url and not url.startswith(("mongodb+srv://", "mongodb://")):
        fail("workflow.env", "MONGO_URL", "must start with mongodb+srv:// or mongodb://")


def check_redis(file_name: str, values: dict[str, str]) -> None:
    url = values.get("REDIS_URL", "")
    if url and not url.startswith("rediss://"):
        fail(file_name, "REDIS_URL", "must start with rediss:// (two s) for TLS")


def check_execution(values: dict[str, str]) -> None:
    file_name = "execution.env"
    if values.get("WORKFLOW_SERVICE_URL") and values["WORKFLOW_SERVICE_URL"] != "http://workflow:8000":
        fail(file_name, "WORKFLOW_SERVICE_URL", "should be http://workflow:8000 for the compose setup")
    if values.get("RUN_QUEUE_BACKEND") and values["RUN_QUEUE_BACKEND"] != "sqs":
        notes.append("NOTE     execution.env  RUN_QUEUE_BACKEND is not sqs, the local queue will be used")
    queue_url = values.get("SQS_QUEUE_URL", "")
    region = values.get("AWS_REGION", "")
    if queue_url:
        host = urlsplit(queue_url).hostname or ""
        if not host.startswith("sqs.") or not host.endswith(".amazonaws.com"):
            fail(file_name, "SQS_QUEUE_URL", "does not look like an SQS queue URL")
        elif region and f"sqs.{region}." not in host:
            fail(file_name, "SQS_QUEUE_URL", "region does not match AWS_REGION")
    if values.get("ALLOW_LOCAL_FILES", "false").lower() == "true":
        notes.append("NOTE     execution.env  ALLOW_LOCAL_FILES is true, workflows can read the local files folder")
    base_url = values.get("OPENAI_BASE_URL", "")
    if base_url and not base_url.startswith("https://"):
        fail(file_name, "OPENAI_BASE_URL", "must start with https://")


def check_smtp(file_name: str, values: dict[str, str]) -> None:
    if not values.get("SMTP_HOST"):
        notes.append(f"NOTE     {file_name}  SMTP_HOST is empty, OTP codes and emails will only be logged")
        return
    for key in ("SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
        if not values.get(key):
            fail(file_name, key, "is empty but SMTP_HOST is set")
    password = values.get("SMTP_PASSWORD", "")
    if values.get("SMTP_HOST") == "smtp.gmail.com" and password:
        compact = password.replace(" ", "")
        if len(compact) != 16:
            fail(file_name, "SMTP_PASSWORD", f"a Gmail app password has 16 letters, found {len(compact)}")
        elif " " in password:
            notes.append(f"NOTE     {file_name}  SMTP_PASSWORD contains spaces, Google ignores them but removing them is safer")
def check_shared(all_values: dict[str, dict[str, str]]) -> None:
    for key in ("JWT_SECRET", "INTERNAL_SERVICE_TOKEN", "REDIS_URL"):
        found = {name: values[key] for name, values in all_values.items() if values.get(key)}
        if len(set(found.values())) > 1:
            fail("all files", key, "must be identical in every file but differs")
    jwt_secret = all_values["auth.env"].get("JWT_SECRET")
    internal_token = all_values["auth.env"].get("INTERNAL_SERVICE_TOKEN")
    otp_secret = all_values["auth.env"].get("OTP_SECRET")
    if jwt_secret and internal_token and jwt_secret == internal_token:
        fail("auth.env", "JWT_SECRET", "must not equal INTERNAL_SERVICE_TOKEN")
    if otp_secret and otp_secret in (jwt_secret, internal_token):
        fail("auth.env", "OTP_SECRET", "must be different from the other two secrets")
    auth_host = urlsplit(all_values["auth.env"].get("DATABASE_URL", "").replace("+asyncpg", "", 1)).hostname
    execution_host = urlsplit(all_values["execution.env"].get("DATABASE_URL", "").replace("+asyncpg", "", 1)).hostname
    if auth_host and execution_host and auth_host != execution_host:
        notes.append("NOTE     DATABASE_URL hosts differ between auth and execution (fine if you use two Neon projects)")


def main() -> int:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    all_values: dict[str, dict[str, str]] = {}
    for file_name in REQUIRED_KEYS:
        path = folder / file_name
        if not path.exists():
            fail(file_name, "-", "file not found")
            continue
        all_values[file_name] = parse_env_file(path, file_name)

    if len(all_values) == len(REQUIRED_KEYS):
        for file_name, values in all_values.items():
            check_required(file_name, values)
            check_secret_strength(file_name, values)
            check_redis(file_name, values)
        check_postgres("auth.env", all_values["auth.env"], "auth_db")
        check_postgres("execution.env", all_values["execution.env"], "execution_db")
        check_mongo(all_values["workflow.env"])
        check_execution(all_values["execution.env"])
        check_smtp("auth.env", all_values["auth.env"])
        check_smtp("execution.env", all_values["execution.env"])
        check_shared(all_values)

    for line in problems + notes:
        print(line)
    if problems:
        print(f"\n{len(problems)} problem(s) found. Fix them and run again.")
        return 1
    print("\nAll checks passed. No values were printed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())