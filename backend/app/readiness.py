"""Container worker health probe: python -m app.readiness."""
from app.services.runtime_health import this_worker_ready

if __name__ == '__main__':
    raise SystemExit(0 if this_worker_ready() else 1)
