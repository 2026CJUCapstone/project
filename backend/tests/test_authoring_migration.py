"""Additive authoring migration with explicit isolated database fixtures."""
from sqlalchemy import inspect, text

from app.initialize import initialize, RUNTIME_SCHEMA_VERSION
from tests.test_worker_schema_migration import legacy_execution_engine, _create_legacy_execution_jobs, _execution_job_snapshot


def test_v13_marker_and_existing_jobs_survive_v14_and_repeat(legacy_execution_engine):
    engine=legacy_execution_engine
    _create_legacy_execution_jobs(engine)
    before=_execution_job_snapshot(engine,include_worker_id=False)
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE schema_migrations (version VARCHAR PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'))
        connection.execute(text("INSERT INTO schema_migrations (version) VALUES ('20260926_resource_budget_v13')"))
    initialize(bind=engine)
    initialize(bind=engine)
    assert _execution_job_snapshot(engine,include_worker_id=False)==before
    inspector=inspect(engine)
    for name in ('problem_authoring','problem_review_events','problem_validation_attestations','contest_package_imports'):
        assert name in inspector.get_table_names()
    with engine.connect() as connection:
        versions=list(connection.execute(text('SELECT version FROM schema_migrations')).scalars())
        assert versions.count('20260926_resource_budget_v13')==0
        assert versions.count(RUNTIME_SCHEMA_VERSION)==1
        assert connection.execute(text('SELECT 1 FROM runtime_schema_history WHERE version=:v'),
                                  {'v':'20260926_resource_budget_v13'}).first()
        for name in ('problem_authoring','problem_review_events','problem_validation_attestations','contest_package_imports'):
            assert connection.execute(text(f'SELECT COUNT(*) FROM {name}')).scalar_one()==0
