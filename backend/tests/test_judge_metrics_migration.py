from sqlalchemy import inspect,text
from app.initialize import initialize,RUNTIME_SCHEMA_VERSION
from app.models import database as m
from tests.test_durable_queue import replicas
from tests.test_judge_metrics import seed


def test_v15_additive_null_metrics_preserve_existing_rows_and_markers(replicas):
    queue,job_id,payload,model=seed(replicas[0],'contest')
    with replicas[0]() as db:
        db.get(m.User,'owner').role='admin'
        db.commit()
    engine=replicas[0].kw['bind']
    with engine.begin() as connection:
        for name in ('submissions','contest_submissions'):
            connection.execute(text(f'ALTER TABLE {name} DROP COLUMN resource_report'))
        connection.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR PRIMARY KEY)'))
        connection.execute(text("INSERT INTO schema_migrations (version) VALUES ('20260926_authoring_packages_v14')"))
    initialize(bind=engine,skip_bootstrap=True)
    initialize(bind=engine,skip_bootstrap=True)
    for name in ('submissions','contest_submissions'):
        columns={c['name']:c for c in inspect(engine).get_columns(name)}
        assert columns['resource_report']['nullable'] is True
    with replicas[1]() as db:
        row=db.get(model,'s')
        assert row.code=='private source' and row.verdict=='pending' and row.resource_report is None
        assert db.get(m.ExecutionJob,job_id).payload==payload
        versions=list(db.execute(text('SELECT version FROM schema_migrations')).scalars())
        assert versions.count(RUNTIME_SCHEMA_VERSION)==1 and '20260926_authoring_packages_v14' not in versions
        assert db.execute(text('SELECT 1 FROM runtime_schema_history WHERE version=:v'),
                          {'v':'20260926_authoring_packages_v14'}).first()
