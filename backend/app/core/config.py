import json
import re
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "B++ Compiler API"
    VERSION: str = "1.0.0"
    # Set from the verified source revision, not a mutable branch/tag. Empty
    # means an unversioned local run; do not invent a successful deployment ID.
    DEPLOYMENT_SHA: str = ""
    # Readiness belongs to one deployment color, even for identical releases.
    # This is not the sandbox/queue namespace: those remain shared for recovery.
    RUNTIME_POOL_ID: str = "local"
    RUNTIME_INSTANCE_ID: str = ""
    WORKER_STATE_DIRECTORY: str = ""
    RUNTIME_MAX_ACTIVE_REQUESTS: int = 512
    TRUSTED_PROXY_CIDRS: str = ""
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    # Production APIs never migrate/seed or execute sandboxes. Development can
    # keep one-process startup, but still uses the same durable database queue.
    AUTO_INITIALIZE_DB: bool | None = None
    EMBEDDED_EXECUTION_WORKER: bool | None = None
    WORKER_DRAIN_SECONDS: float = 135

    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173", "http://127.0.0.1:5174"]

    SANDBOX_IMAGE: str = "compiler-sandbox"
    SANDBOX_POOL_ID: str = "webcompiler"
    EXECUTION_TIMEOUT: int = 30
    SANDBOX_WORKDIR_ROOT: str = "/tmp/compiler-sandbox"
    SANDBOX_MEMORY_MB: int = 256
    SANDBOX_CPU_LIMIT: float = 1.0
    SANDBOX_PIDS_LIMIT: int = 64
    SANDBOX_NOFILE_LIMIT: int = 1024
    SANDBOX_OUTPUT_MAX_BYTES: int = 1_048_576
    TERMINAL_SESSION_TIMEOUT: int = 120
    TERMINAL_START_TIMEOUT: float = 5
    TERMINAL_MAX_CONNECTIONS: int = 32
    TERMINAL_MAX_CONNECTIONS_PER_IDENTITY: int = 4
    TERMINAL_CONNECTION_LEASE_SECONDS: int = 15
    TERMINAL_INPUT_MAX_BYTES: int = 65_536
    SECRET_KEY: str | None = None
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str | None = None
    ADMIN_NICKNAME: str = "관리자"
    AUTH_RATE_LIMIT_MAX_ATTEMPTS: int = 8
    AUTH_IP_RATE_LIMIT_MAX_ATTEMPTS: int = 60
    AUTH_RATE_LIMIT_WINDOW_SECONDS: int = 60
    CODE_PROJECT_MAX_BYTES: int = 200_000
    CODE_PROJECT_MAX_PER_USER: int = 100
    CODE_PROJECT_SCOPE_MAX_LENGTH: int = 128
    SUBMISSION_CODE_MAX_BYTES: int = 200_000
    EXECUTION_STDIN_MAX_BYTES: int = 65_536
    EXECUTION_IP_RATE_LIMIT: int = 30
    EXECUTION_USER_RATE_LIMIT: int = 30
    EXECUTION_GLOBAL_RATE_LIMIT: int = 300
    SUBMISSION_RETENTION_PER_USER: int = 200
    ANONYMOUS_SUBMISSION_RETENTION_DAYS: int = 7
    # An operator/user-approved policy is required before removing job content.
    # Zero disables only this content scrub, not existing submission retention.
    EXECUTION_CONTENT_RETENTION_DAYS: int = Field(default=0, ge=0, le=3650)
    COMPILER_QUEUE_CONCURRENCY: int = 2
    EXECUTION_QUEUE_CAPACITY: int = 200
    EXECUTION_QUEUE_PER_OWNER: int = 4
    EXECUTION_LEASE_SECONDS: int = 120
    EXECUTION_JOB_TIMEOUT_SECONDS: float = 120
    COMPILER_QUEUE_HISTORY_LIMIT: int = Field(default=500, ge=0, le=10_000)
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

    @field_validator("DEPLOYMENT_SHA")
    @classmethod
    def validate_deployment_sha(cls, value: str) -> str:
        if value and re.fullmatch(r"[0-9a-f]{40}", value) is None:
            raise ValueError("DEPLOYMENT_SHA must be an exact lowercase Git commit SHA")
        return value

    @field_validator("TRUSTED_PROXY_CIDRS")
    @classmethod
    def validate_proxy_networks(cls, value):
        from app.services.trusted_ingress import trusted_networks
        return ','.join(str(network) for network in trusted_networks(value))

    @field_validator("RUNTIME_POOL_ID")
    @classmethod
    def validate_runtime_pool_id(cls, value: str) -> str:
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", value) is None:
            raise ValueError("RUNTIME_POOL_ID must be a lowercase resource identifier of 1-80 characters")
        return value

    @field_validator("RUNTIME_INSTANCE_ID", mode="before")
    @classmethod
    def validate_runtime_instance_id(cls, value: str) -> str:
        from app.services.runtime_identity import validate_runtime_id
        return validate_runtime_id(value, allow_empty=True)

    @field_validator("WORKER_STATE_DIRECTORY", mode="before")
    @classmethod
    def validate_worker_state_directory(cls, value: str) -> str:
        from pathlib import Path
        if not isinstance(value,str) or '\x00' in value or (value and not Path(value).is_absolute()):
            raise ValueError('WORKER_STATE_DIRECTORY must be empty or an absolute path')
        return value

    @field_validator("RUNTIME_MAX_ACTIVE_REQUESTS", mode="before")
    @classmethod
    def validate_runtime_request_limit(cls, value):
        if isinstance(value,str) and re.fullmatch('[0-9]+',value):
            value = int(value)
        if type(value) is not int or not 1 <= value <= 4096:
            raise ValueError('RUNTIME_MAX_ACTIVE_REQUESTS must be an integer from 1 to 4096')
        return value

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
