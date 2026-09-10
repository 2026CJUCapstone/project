import json
import os
import uuid
from datetime import datetime

import pytest
from sqlalchemy import Column, DateTime, Integer, JSON, MetaData, String, Table, UniqueConstraint, create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError

from app.core import database
import app.models.database  # Register current metadata before init_db creates new tables.


@pytest.fixture(params=['sqlite', 'postgres'])
def legacy_execution_engine(tmp_path, request):
    """An isolated pre-worker schema, matching the durable-queue replica fixture."""
    control = None
    schema = None
    if request.param == 'postgres':
        url = os.getenv('TEST_POSTGRES_URL')
        if not url:
            pytest.skip('Explicit isolated PostgreSQL test URL required')
        schema = f'audit_worker_schema_{uuid.uuid4().hex}'
        control = create_engine(url)
        with control.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        test_engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    else:
        test_engine = create_engine(
            f"sqlite:///{(tmp_path / 'legacy-workers.db').as_posix()}",
            connect_args={'check_same_thread': False},
        )

        @event.listens_for(test_engine, 'connect')
        def enforce_foreign_keys(connection, _record):
            connection.execute('PRAGMA foreign_keys=ON')

    try:
        yield test_engine
    finally:
        test_engine.dispose()
        if control is not None:
            # Remove only this generated fixture schema, never a shared/public schema.
            assert schema.startswith('audit_worker_schema_') and len(schema) == 52
            with control.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            control.dispose()


def _create_legacy_execution_jobs(engine):
    metadata = MetaData()
    jobs = Table(
        'execution_jobs',
        metadata,
        Column('id', String, primary_key=True),
        Column('owner_key', String, nullable=False, index=True),
        Column('quota_key', String, nullable=False, index=True),
        Column('request_id', String, nullable=False),
        Column('payload_hash', String, nullable=False),
        Column('kind', String, nullable=False),
        Column('payload', JSON, nullable=False),
        Column('result', JSON, nullable=True),
        Column('status', String, nullable=False, index=True),
        Column('received_at', DateTime, nullable=False, index=True),
        Column('started_at', DateTime, nullable=True),
        Column('finished_at', DateTime, nullable=True),
        Column('lease_token', String, nullable=True),
        Column('lease_until', DateTime, nullable=True, index=True),
        Column('attempts', Integer, nullable=False),
        UniqueConstraint('owner_key', 'request_id', name='uq_execution_owner_request'),
    )
    metadata.create_all(engine)
    received_at = datetime(2030, 1, 2, 3, 4, 5)
    with engine.begin() as connection:
        connection.execute(
            jobs.insert(),
            [
                {
                    'id': 'queued',
                    'owner_key': 'owner-queued',
                    'quota_key': 'quota-queued',
                    'request_id': 'request-queued',
                    'payload_hash': 'hash-queued',
                    'kind': 'run',
                    'payload': {'source': 'queued', 'stdin': 'one'},
                    'result': None,
                    'status': 'queued',
                    'received_at': received_at,
                    'started_at': None,
                    'finished_at': None,
                    'lease_token': None,
                    'lease_until': None,
                    'attempts': 0,
                },
                {
                    'id': 'running',
                    'owner_key': 'owner-running',
                    'quota_key': 'quota-running',
                    'request_id': 'request-running',
                    'payload_hash': 'hash-running',
                    'kind': 'run',
                    'payload': {'source': 'running', 'stdin': 'two'},
                    'result': None,
                    'status': 'running',
                    'received_at': received_at,
                    'started_at': received_at,
                    'finished_at': None,
                    'lease_token': 'legacy-lease-token',
                    'lease_until': received_at,
                    'attempts': 1,
                },
                {
                    'id': 'completed',
                    'owner_key': 'owner-completed',
                    'quota_key': 'quota-completed',
                    'request_id': 'request-completed',
                    'payload_hash': 'hash-completed',
                    'kind': 'run',
                    'payload': {'source': 'completed', 'stdin': 'three'},
                    'result': {'verdict': 'accepted', 'stdout': '3'},
                    'status': 'completed',
                    'received_at': received_at,
                    'started_at': received_at,
                    'finished_at': received_at,
                    'lease_token': None,
                    'lease_until': None,
                    'attempts': 1,
                },
            ],
        )


def _timestamp_value(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.isoformat() if value is not None else None


def _execution_job_snapshot(engine, *, include_worker_id=True):
    columns = [
        'id', 'owner_key', 'quota_key', 'request_id', 'payload_hash', 'kind', 'payload', 'result',
        'status', 'received_at', 'started_at', 'finished_at', 'lease_token', 'lease_until', 'attempts',
    ]
    if include_worker_id:
        columns.append('worker_id')
    with engine.connect() as connection:
        rows = connection.execute(
            text(f"SELECT {', '.join(columns)} FROM execution_jobs ORDER BY id")
        ).mappings()
        snapshot = {}
        for row in rows:
            record = {
                'owner_key': row['owner_key'],
                'quota_key': row['quota_key'],
                'request_id': row['request_id'],
                'payload_hash': row['payload_hash'],
                'kind': row['kind'],
                'payload': json.loads(row['payload']) if isinstance(row['payload'], str) else row['payload'],
                'result': json.loads(row['result']) if isinstance(row['result'], str) else row['result'],
                'status': row['status'],
                'received_at': _timestamp_value(row['received_at']),
                'started_at': _timestamp_value(row['started_at']),
                'finished_at': _timestamp_value(row['finished_at']),
                'lease_token': row['lease_token'],
                'lease_until': _timestamp_value(row['lease_until']),
                'attempts': row['attempts'],
            }
            if include_worker_id:
                record['worker_id'] = row['worker_id']
            snapshot[row['id']] = record
        return snapshot


def test_init_db_adds_nullable_worker_owner_without_changing_legacy_execution_jobs(legacy_execution_engine):
    _create_legacy_execution_jobs(legacy_execution_engine)
    before = inspect(legacy_execution_engine)
    assert 'worker_id' not in {column['name'] for column in before.get_columns('execution_jobs')}
    legacy_values = _execution_job_snapshot(legacy_execution_engine, include_worker_id=False)

    database.init_db(legacy_execution_engine)

    inspector = inspect(legacy_execution_engine)
    worker_columns = {column['name']: column for column in inspector.get_columns('execution_workers')}
    assert {'id', 'pool_id', 'deployment_sha', 'sandbox_pool_id', 'started_at', 'draining_at'} <= set(worker_columns)
    assert inspector.get_pk_constraint('execution_workers')['constrained_columns'] == ['id']

    job_columns = {column['name']: column for column in inspector.get_columns('execution_jobs')}
    assert job_columns['worker_id']['nullable']
    assert any(
        index.get('column_names') == ['worker_id']
        for index in inspector.get_indexes('execution_jobs')
    )
    assert any(
        index.get('column_names') == ['pool_id']
        for index in inspector.get_indexes('execution_workers')
    )
    assert any(
        foreign_key.get('constrained_columns') == ['worker_id']
        and foreign_key.get('referred_table') == 'execution_workers'
        and foreign_key.get('referred_columns') == ['id']
        for foreign_key in inspector.get_foreign_keys('execution_jobs')
    )
    with pytest.raises(IntegrityError):
        with legacy_execution_engine.begin() as connection:
            connection.execute(
                text("UPDATE execution_jobs SET worker_id = 'unknown-worker' WHERE id = 'queued'")
            )

    expected = {
        'completed': {
            'owner_key': 'owner-completed',
            'quota_key': 'quota-completed',
            'request_id': 'request-completed',
            'payload_hash': 'hash-completed',
            'kind': 'run',
            'payload': {'source': 'completed', 'stdin': 'three'},
            'result': {'verdict': 'accepted', 'stdout': '3'},
            'status': 'completed',
            'received_at': '2030-01-02T03:04:05',
            'started_at': '2030-01-02T03:04:05',
            'finished_at': '2030-01-02T03:04:05',
            'lease_token': None,
            'lease_until': None,
            'attempts': 1,
            'worker_id': None,
        },
        'queued': {
            'owner_key': 'owner-queued',
            'quota_key': 'quota-queued',
            'request_id': 'request-queued',
            'payload_hash': 'hash-queued',
            'kind': 'run',
            'payload': {'source': 'queued', 'stdin': 'one'},
            'result': None,
            'status': 'queued',
            'received_at': '2030-01-02T03:04:05',
            'started_at': None,
            'finished_at': None,
            'lease_token': None,
            'lease_until': None,
            'attempts': 0,
            'worker_id': None,
        },
        'running': {
            'owner_key': 'owner-running',
            'quota_key': 'quota-running',
            'request_id': 'request-running',
            'payload_hash': 'hash-running',
            'kind': 'run',
            'payload': {'source': 'running', 'stdin': 'two'},
            'result': None,
            'status': 'running',
            'received_at': '2030-01-02T03:04:05',
            'started_at': '2030-01-02T03:04:05',
            'finished_at': None,
            'lease_token': 'legacy-lease-token',
            'lease_until': '2030-01-02T03:04:05',
            'attempts': 1,
            'worker_id': None,
        },
    }
    first_snapshot = _execution_job_snapshot(legacy_execution_engine)
    assert {
        job_id: {key: value for key, value in record.items() if key != 'worker_id'}
        for job_id, record in first_snapshot.items()
    } == legacy_values
    assert first_snapshot == expected

    database.init_db(legacy_execution_engine)

    assert _execution_job_snapshot(legacy_execution_engine) == expected
    worker_indexes = [
        index for index in inspect(legacy_execution_engine).get_indexes('execution_jobs')
        if index.get('column_names') == ['worker_id']
    ]
    assert len(worker_indexes) == 1
