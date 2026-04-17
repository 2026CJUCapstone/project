import json
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "B++ Compiler API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173", "http://localhost:5174"]

    SANDBOX_IMAGE: str = "compiler-sandbox"
    EXECUTION_TIMEOUT: int = 10
    SANDBOX_WORKDIR_ROOT: str = "/tmp/compiler-sandbox"
    SANDBOX_MEMORY_MB: int = 256
    SANDBOX_CPU_LIMIT: float = 1.0
    SANDBOX_PIDS_LIMIT: int = 64
    SANDBOX_NOFILE_LIMIT: int = 1024

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
