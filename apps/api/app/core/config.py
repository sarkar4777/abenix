import logging
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# Load .env from project root if it exists
_env_file = Path(__file__).resolve().parents[4] / ".env"


class Settings(BaseSettings):
    app_name: str = "Abenix API"
    debug: bool = False
    database_url: str = "postgresql+asyncpg://abenix:abenix@localhost:5432/abenix"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str = "change-me-in-production"
    cors_origins: list[str] = ["http://localhost:3000"]
    frontend_url: str = "http://localhost:3000"

    log_level: str = "INFO"
    otel_enabled: bool = False
    otel_exporter: str = "stdout"
    otel_endpoint: str = "http://localhost:4317"

    jwt_private_key: str = ""
    jwt_public_key: str = ""
    jwt_algorithm: str = "RS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # LLM Provider keys (read from .env)
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    google_api_key: str = ""

    # Stripe
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_connect_client_id: str = ""

    # Wave-2 scaling — when True, agent executions with a non-inline
    # `runtime_pool` are enqueued on the configured queue backend instead
    # of running in the API process. Consumers in per-pool Deployments
    # pick them up and execute. Defaults OFF so behaviour is unchanged.
    scaling_exec_remote: bool = False
    queue_backend: str = "celery"  # celery | nats — also read by the agent-runtime consumer

    model_config = {
        "env_prefix": "",
        "case_sensitive": False,
        "env_file": str(_env_file) if _env_file.exists() else None,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def _validate_production_settings(self) -> "Settings":
        if not self.debug:
            if self.secret_key == "change-me-in-production":
                raise RuntimeError("SECRET_KEY must be changed in production")
            if not self.jwt_private_key and not self.jwt_public_key:
                raise RuntimeError("JWT keys must be configured in production")
        if "*" in self.cors_origins:
            logger.warning("CORS wildcard origin with credentials is insecure")
        if not any([self.anthropic_api_key, self.openai_api_key, self.google_api_key]):
            logger.warning("No LLM API key is set (anthropic, openai, or google)")
        return self


settings = Settings()
