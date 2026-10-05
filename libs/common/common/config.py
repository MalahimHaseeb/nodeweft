from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CommonSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "production"
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "nodeweft"
    access_token_minutes: int = 15
    redis_url: str = "redis://localhost:6379/0"
    trusted_proxy_hops: int = 1
    internal_service_token: str
    cors_origins: str = ""
    max_body_bytes: int = 2_000_000

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @model_validator(mode="after")
    def reject_weak_secrets_in_production(self):
        if self.is_production:
            if len(self.jwt_secret) < 32 or len(self.internal_service_token) < 32:
                raise ValueError("jwt_secret and internal_service_token must be at least 32 characters in production")
        return self
