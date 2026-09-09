"""Local-only browser test fixture. NOT imported by the production application.

Run from backend: python tests/contest_browser_server.py
Uses a NEW temporary SQLite DB and fake sandbox, but real auth/API/queue/workers.
"""
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
test_dir = Path(tempfile.mkdtemp(prefix='bpp-contest-e2e-'))
os.environ.update(DATABASE_URL=f"sqlite:///{(test_dir / 'test.db').as_posix()}",
                  ENVIRONMENT='development', SECRET_KEY='local-contest-test-key-not-for-production',
                  ADMIN_USERNAME='contest_admin', ADMIN_PASSWORD='LocalContestTest!123', REDIS_URL='',
                  CORS_ORIGINS='http://127.0.0.1:4175', COMPILER_QUEUE_CONCURRENCY='2')

from app.main import app
from app.core.database import SessionLocal
from app.models.database import User
from app.services.auth import get_password_hash
from app.api.routes import contests as routes
from app.services import contests, contest_access

clock = [datetime(2030, 1, 1)]
for module in (routes, contests, contest_access):
    module.now_utc = lambda: clock[0]

async def fake_compile(**kwargs):
    return {'exit_code': 1 if 'COMPILE_ERROR' in kwargs['source_code'] else 0,
            'stdout':'', 'stderr':'', 'execution_time':1}

async def fake_run(**kwargs):
    return {'exit_code':0, 'stdout':'0' if 'WRONG_ANSWER' in kwargs['source_code'] else '42',
            'stderr':'', 'execution_time':1}

contests.compiler_service.compiler_instance._execute = fake_compile
contests.compiler_service.compiler_instance.run = fake_run
with SessionLocal() as db:
    db.add(User(username='contest_solver', hashed_password=get_password_hash('LocalContestTest!123'), role='user'))
    db.commit()

@app.post('/__test/clock')
def set_test_clock(body: dict):
    clock[0] = datetime.fromisoformat(body['at']).replace(tzinfo=None)
    return {'serverTime': contest_access.iso(clock[0])}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=18001)
