from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import admin, community, compiler, problems, projects, terminal, auth
from app.core.bootstrap import bootstrap_application_data
from app.core.database import SessionLocal, init_db
from app.services import auth as auth_service

auth_service.validate_runtime_security()
init_db()
with SessionLocal() as bootstrap_db:
    bootstrap_application_data(bootstrap_db)

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
app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])

@app.get("/health")
def health_check():
    return {"status": "ok", "version": settings.VERSION}
