from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import compiler, problems, terminal
from app.core.database import engine, Base

Base.metadata.create_all(bind=engine)

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
app.include_router(problems.router, prefix="/api/v1/problems", tags=["problems"])
app.include_router(compiler.router, prefix="/api/v1/compiler", tags=["compiler"])
app.include_router(terminal.router, tags=["terminal"])

@app.get("/health")
def health_check():
    return {"status": "ok", "version": settings.VERSION}
