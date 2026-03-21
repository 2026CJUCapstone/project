from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import compiler
from app.core.config import settings

app = FastAPI(
    title="Online Compiler API",
    description="코드 컴파일 및 실행 API 서버",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(compiler.router, prefix="/api/v1/compiler", tags=["compiler"])


@app.get("/health")
def health_check():
    return {"status": "ok"}
