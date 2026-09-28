"""Local-only real HTTP/SQLite history fixture; no execution or production data.

Run from backend with the test dependencies installed. Port 18003.
"""
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
test_dir = Path(tempfile.mkdtemp(prefix='bpp-history-e2e-'))
os.environ.update(
    DATABASE_URL=f"sqlite:///{(test_dir / 'test.db').as_posix()}",
    ENVIRONMENT='development', SECRET_KEY='local-history-fixture-not-production',
    ADMIN_USERNAME='history_admin', ADMIN_PASSWORD='LocalHistoryTest!123',
    REDIS_URL='', AUTO_INITIALIZE_DB='true', EMBEDDED_EXECUTION_WORKER='false',
    CORS_ORIGINS='http://127.0.0.1:4180', RUNTIME_INSTANCE_ID='',
    RUNTIME_POOL_ID='local-history-fixture', SANDBOX_POOL_ID='local-history-fixture',
)

from app.main import app
from app.core.database import SessionLocal
from app.models import database as m
from app.services.auth import get_password_hash

now = datetime.now(timezone.utc).replace(tzinfo=None)
with SessionLocal() as db:
    for name in ('alice', 'bob'):
        db.add(m.User(id=name, username=name,
                      hashed_password=get_password_hash('LocalHistoryTest!123'), role='user'))
    db.flush()
    db.add(m.Problem(id='shared', creator_id='alice', title='공개 연습 문제',
                     description='Fixture', difficulty='bronze5', tags=[], test_cases=[]))
    db.flush()
    for index, title in [('a', '신입생 콘테스트'), ('b', '두 번째 콘테스트')]:
        db.add(m.Contest(id=index, creator_id='alice', title=title, published=True,
                         starts_at=now - timedelta(hours=1), ends_at=now + timedelta(days=1)))
        db.flush()
        db.add(m.ContestProblem(id=f'cp-{index}', contest_id=index, problem_id='shared',
                                position=0, points=100, is_new=False,
                                snapshot={'title': f'{index.upper()} 대회 문제', 'hidden': ['DO_NOT_EXPOSE']}))
        db.add(m.ContestParticipant(contest_id=index, user_id='alice'))
        db.add(m.ContestParticipant(contest_id=index, user_id='bob'))
        db.flush()
        for name in ('alice', 'bob'):
            db.add(m.ContestSubmission(id=f'{name}-{index}', user_id=name, contest_id=index,
                                       contest_problem_id=f'cp-{index}', request_id=f'{name}-{index}',
                                       code='PRIVATE_SOURCE', language='python', status='completed',
                                       verdict='accepted', received_at=now, finished_at=now))
    for index in range(55):
        db.add(m.CompileQueueRecord(id=f'public-{index:02}', user_id='alice', username='alice',
                                    problem_id='shared' if index % 2 else None,
                                    problem_title='공개 연습 문제' if index % 2 else None,
                                    kind='grading' if index % 2 else 'run', language='cpp',
                                    status='completed', verdict='finished', source_size_bytes=7,
                                    queued_at=now - timedelta(seconds=index + 1)))
    db.commit()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=18003)
