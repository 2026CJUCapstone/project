from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import compiler, problems, terminal, auth, community
from app.core.database import engine, Base

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
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
app.include_router(terminal.router, prefix="/ws", tags=["terminal"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(community.router, prefix="/api/v1/community", tags=["community"])

@app.get("/health")
def health_check():
    return {"status": "ok", "version": settings.VERSION}
