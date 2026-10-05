import os

os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-123")
os.environ.setdefault("INTERNAL_SERVICE_TOKEN", "internal-token-internal-token-internal-123")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
