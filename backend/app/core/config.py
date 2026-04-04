from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    PROJECT_NAME: str = "B++ Compiler API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    SANDBOX_IMAGE: str = "compiler-sandbox"
    EXECUTION_TIMEOUT: int = 10

    class Config:
        env_file = ".env"


settings = Settings()
