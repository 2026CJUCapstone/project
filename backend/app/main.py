from fastapi import FastAPI
from app.core.config import settings
from app.api.routes import compiler

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="코드 컴파일 및 실행 API 서버",
    version=settings.VERSION
)

app.include_router(compiler.router, prefix=settings.API_V1_STR)

@app.get("/")
def read_root():
    return {"message": f"Welcome to {settings.PROJECT_NAME}!"}

@app.get("/health")
def health_check():
    return {"status": "ok"}
