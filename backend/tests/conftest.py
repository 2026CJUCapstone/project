import pytest


@pytest.fixture
def contest_engine(tmp_path, request):
    """SQLite by default; explicit indirect PG tests own a disposable schema."""
    import os
    from uuid import uuid4
    from sqlalchemy import create_engine, text
    backend = getattr(request, 'param', 'sqlite')
    if backend == 'sqlite':
        engine = create_engine(f"sqlite:///{(tmp_path / 'contest.db').as_posix()}", connect_args={"check_same_thread": False})
        try:
            yield engine
        finally:
            engine.dispose()
        return
    if backend != 'postgres':
        raise ValueError('Unknown contest test database')
    url = os.getenv('TEST_POSTGRES_URL')
    if not url:
        pytest.skip('Explicit isolated PostgreSQL test URL required')
    schema = 'audit_contest_' + uuid4().hex
    control = create_engine(url)
    engine = None
    created = False
    try:
        with control.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        try:
            if created:
                assert schema.startswith('audit_contest_') and len(schema) == 46
                with control.begin() as conn:
                    conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            control.dispose()


@pytest.fixture(autouse=True)
def isolate_process_local_rate_budgets():
    """Each test models its own clock/traffic, never a previous test's requests."""
    from app.core import rate_limit
    with rate_limit._lock:
        rate_limit._attempts.clear()
        rate_limit._expirations.clear()
        rate_limit._next_cleanup = 0
    yield
