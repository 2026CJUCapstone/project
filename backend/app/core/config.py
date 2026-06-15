import json
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "B++ Compiler API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"

    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173", "http://localhost:5174"]

    SANDBOX_IMAGE: str = "compiler-sandbox"
    EXECUTION_TIMEOUT: int = 30
    SANDBOX_WORKDIR_ROOT: str = "/tmp/compiler-sandbox"
    SANDBOX_MEMORY_MB: int = 256
    SANDBOX_CPU_LIMIT: float = 1.0
    SANDBOX_PIDS_LIMIT: int = 64
    SANDBOX_NOFILE_LIMIT: int = 1024
    TERMINAL_SESSION_TIMEOUT: int = 120
    SECRET_KEY: str | None = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str | None = None
    ADMIN_NICKNAME: str = "관리자"
    AUTH_RATE_LIMIT_MAX_ATTEMPTS: int = 8
    AUTH_RATE_LIMIT_WINDOW_SECONDS: int = 60
    CODE_PROJECT_MAX_BYTES: int = 200_000
    CODE_PROJECT_MAX_PER_USER: int = 100
    CODE_PROJECT_SCOPE_MAX_LENGTH: int = 128
    SUBMISSION_CODE_MAX_BYTES: int = 200_000
    SUBMISSION_RETENTION_PER_USER: int = 200
    COMPILER_QUEUE_CONCURRENCY: int = 2
    COMPILER_QUEUE_HISTORY_LIMIT: int = 500
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 30
    PASSWORD_RESET_BASE_URL: str | None = None
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str | None = None
    SMTP_STARTTLS: bool = True
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_RECYCLE_SECONDS: int = 1800
    REDIS_URL: str | None = None
    REDIS_KEY_PREFIX: str = "webcompiler"
    REDIS_CACHE_TTL_SECONDS: int = 30
    REDIS_QUEUE_POLL_INTERVAL_SECONDS: float = 0.05
    REDIS_QUEUE_HEARTBEAT_SECONDS: int = 120

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", enable_decoding=False)

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> list[str]:
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            if text.startswith("["):
                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]
        return list(value)


settings = Settings()
