from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import database as m
from app.services.admin_audit import audit_context
from tests.test_durable_queue import replicas


def context(actor):
    return {'actor_id':actor, 'request_id':actor, 'action':f'PATCH /api/v1/admin/users/{actor}', 'mutation':True}


def test_failed_admin_transaction_cannot_leave_an_audit_success(replicas):
    with replicas[0]() as db:
        db.add(m.User(id='first', username='duplicate', hashed_password=''))
        db.commit()
    token = audit_context.set(context('admin'))
    try:
        with replicas[0]() as db:
            db.add(m.User(id='second', username='duplicate', hashed_password=''))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
    finally:
        audit_context.reset(token)
    with replicas[1]() as db:
        assert db.query(m.AdminAuditEvent).count() == 0
        assert db.get(m.User, 'second') is None


def test_parallel_request_contexts_do_not_mix_actor_identity(replicas):
    barrier = Barrier(2)
    def mutate(index):
        actor = f'admin-{index}'
        token = audit_context.set(context(actor))
        try:
            with replicas[index]() as db:
                db.add(m.User(id=actor, username=actor, hashed_password=''))
                barrier.wait()
                db.commit()
        finally:
            audit_context.reset(token)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(mutate, (0,1)))
    with replicas[0]() as db:
        events = db.query(m.AdminAuditEvent).all()
        assert len(events) == 2
        for event in events:
            assert event.request_id == event.actor_id
            assert event.action.endswith('/'+event.actor_id)


def test_savepoint_does_not_create_extra_audit_transaction(replicas):
    token = audit_context.set(context('admin'))
    try:
        with replicas[0]() as db:
            with db.begin_nested():
                db.add(m.User(id='savepoint', username='savepoint', hashed_password=''))
            db.commit()
    finally:
        audit_context.reset(token)
    with replicas[1]() as db:
        assert db.query(m.AdminAuditEvent).count() == 1
