from fastapi import FastAPI
from fastapi.responses import JSONResponse
import asyncio
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes import admin, community, compiler, problems, projects, terminal, auth, contests, executions
from app.services.contests import contest_maintenance
from app.services.execution_runtime import build_worker
from app.services.housekeeping import retention_maintenance
from app.initialize import initialize as initialize_database
from app.services import auth as auth_service
from app.services.admin_audit import AuditContextMiddleware
from app.services.api_admission import RuntimeAdmissionMiddleware
from app.services.trusted_ingress import TrustedIngressMiddleware

auth_service.validate_runtime_security()
initialize = settings.AUTO_INITIALIZE_DB
if initialize is None:
    initialize = settings.ENVIRONMENT != 'production'
if initialize and settings.ENVIRONMENT == 'production':
    raise RuntimeError('Production schema changes require python -m app.initialize')
if initialize:
    # Development uses the same atomic schema/bootstrap/readiness contract.
    # Unfinished legacy executions still require explicit offline recovery.
    initialize_database()

@asynccontextmanager
async def lifespan(app):
    from app.services.runtime_registry import register_configured_runtime
    await asyncio.to_thread(register_configured_runtime)
    embedded = settings.EMBEDDED_EXECUTION_WORKER
    if embedded is None:
        embedded = settings.ENVIRONMENT != 'production'
    if settings.ENVIRONMENT == 'production' and embedded:
        raise RuntimeError('Production APIs must use the separate execution worker')
    from app.services.api_lifecycle import owned_api_lifecycle
    from app.services.worker_lifecycle import owned_worker_lifecycle
    async with AsyncExitStack() as owners:
        runtime_requests = await owners.enter_async_context(owned_api_lifecycle())
        app.state.runtime_requests = runtime_requests
        tasks = []
        health_stop = asyncio.Event()
        embedded_started = False
        worker_lifecycle = None
        try:
            if embedded:
                from app.worker import health_loop, withdraw_worker, start_worker_process, stop_worker_process, revoke_worker_readiness
                worker_lifecycle = await owners.enter_async_context(
                    owned_worker_lifecycle(start_worker_process, stop_worker_process))
                embedded_started = True
                tasks = [asyncio.create_task(contest_maintenance()), asyncio.create_task(retention_maintenance())]
                for _ in range(max(1, settings.COMPILER_QUEUE_CONCURRENCY)):
                    tasks.append(asyncio.create_task(build_worker().run()))
                tasks.append(asyncio.create_task(health_loop(health_stop)))
            yield
        finally:
            health_stop.set()
            try:
                if embedded_started:
                    if worker_lifecycle is not None:
                        with suppress(Exception):
                            await asyncio.to_thread(worker_lifecycle.begin_drain)
                    with suppress(Exception):
                        await asyncio.to_thread(revoke_worker_readiness)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                if embedded_started:
                    with suppress(Exception):
                        await asyncio.to_thread(withdraw_worker)
            finally:
                app.state.runtime_requests = None


app = FastAPI(
    lifespan=lifespan,
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count", "Retry-After"],
)
app.add_middleware(AuditContextMiddleware)
# Admission encloses CORS (including preflight) and the request audit context.
# Its own accounting commits must not become administrator mutation events.
app.add_middleware(RuntimeAdmissionMiddleware)
# Run before admission/audit/auth so all limits use the same validated identity.
app.add_middleware(TrustedIngressMiddleware, networks=settings.TRUSTED_PROXY_CIDRS)

app.include_router(problems.router, prefix="/api/v1/problems", tags=["problems"])
app.include_router(compiler.router, prefix="/api/v1/compiler", tags=["compiler"])
app.include_router(terminal.router, prefix="/ws", tags=["terminal"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(community.router, prefix="/api/v1/community", tags=["community"])
app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["admin"])
app.include_router(contests.router, prefix="/api/v1/contests", tags=["contests"])
app.include_router(executions.router, prefix="/api/v1/executions", tags=["executions"])

@app.get("/health")
def health_check():
    return JSONResponse({"status": "ok", "version": settings.VERSION,
                         "deploymentSha": settings.DEPLOYMENT_SHA or None,
                         "runtimeInstanceId": settings.RUNTIME_INSTANCE_ID or None},
                        headers={'Cache-Control': 'no-store'})


@app.get('/ready')
def readiness_check():
    from app.services.runtime_health import dependencies_ready
    ready = dependencies_ready()
    return JSONResponse({'status':'ready' if ready else 'unavailable'},
        status_code=200 if ready else 503, headers={'Cache-Control':'no-store'})
