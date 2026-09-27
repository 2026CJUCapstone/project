"""Private data storage/upload contracts; no live registration or worker claim."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
from threading import Barrier,Event
from types import SimpleNamespace
import zlib

import pytest
from fastapi import HTTPException
from httpx import ASGITransport,AsyncClient
from starlette.datastructures import Headers
from sqlalchemy import inspect,text

from app.main import app
from app.models import database as m
from app.services import judge_test_data as store
from app.api.routes import judge_test_data as routes
from app.initialize import initialize,RUNTIME_SCHEMA_VERSION
from tests.test_contests import env,headers


def digest(data): return 'sha256:'+hashlib.sha256(data).hexdigest()
def url(data): return '/api/v1/admin/judge-test-data/'+digest(data)[7:]+f'?byteCount={len(data)}'


@pytest.mark.parametrize('data',[b'',b'0\n','한글 \n'.encode(),b'a'*(65536-1)+'한'.encode()],
                         ids=['empty','ascii','korean','split-codepoint'])
def test_storage_roundtrip_and_immutable_exact_retry(env,data):
    with env.factory() as db:
        first=store.put_data(db,data,digest(data),env.admin.id);db.commit()
        assert first==dict(digest=digest(data),byteCount=len(data),encoding='utf-8',replayed=False)
        again=store.put_data(db,data,digest(data),env.admin.id);db.commit()
        assert again=={**first,'replayed':True}
        assert store.load_data(db,digest(data))==data
        assert db.query(m.JudgeTestData).count()==1


@pytest.mark.parametrize('bad', ['../blob','SHA256:'+'a'*64,'sha256:'+'A'*64,'sha256:short',None])
def test_digest_never_becomes_path_or_url(bad):
    with pytest.raises(ValueError): store.validate_bytes(b'x',bad)


@pytest.mark.parametrize('data',[b'\xff',b'\xed\xa0\x80',b'\xe3\x81'])
def test_non_utf8_is_rejected(data):
    with pytest.raises(ValueError): store.validate_bytes(data,digest(data))


def test_maximum_c_statement_input_is_stored_once_and_read_back(env):
    # Actual C statement N=1e6, every value=-1e6, ~9MB including separators.
    data=b'1000000\n'+b'-1000000 '*999999+b'-1000000\n'
    assert 8_000_000<len(data)<store.MAX_DATA_BYTES
    with env.factory() as db:
        store.put_data(db,data,digest(data),env.admin.id);db.commit()
    with env.factory() as db:
        assert store.load_data(db,digest(data))==data
        assert db.query(m.ExecutionJob).count()==db.query(m.Contest).count()==0


def test_exact_byte_cap_and_one_more_rejected():
    data=b'a'*store.MAX_DATA_BYTES
    store.validate_bytes(data,digest(data))
    with pytest.raises(ValueError,match='limit'): store.validate_bytes(data+b'a',digest(data+b'a'))
    with pytest.raises(ValueError,match='digest'): store.validate_bytes(b'x',digest(b'y'))


@pytest.mark.parametrize('mutation', ['missing','truncated','trailing','oversized','bad-count','hash','utf8'])
def test_corruption_is_not_repaired_or_decompressed_unbounded(env,mutation):
    data=b'valid UTF-8\n';key=digest(data)
    with env.factory() as db:
        if mutation=='missing':
            with pytest.raises(ValueError,match='missing'): store.load_data(db,key)
            return
        store.put_data(db,data,key,env.admin.id);db.commit()
        row=db.get(m.JudgeTestData,key)
        if mutation=='truncated': row.compressed=row.compressed[:-1]
        if mutation=='trailing': row.compressed+=b'trailing'
        if mutation=='oversized': row.compressed=zlib.compress(b'a'*(store.MAX_DATA_BYTES+1));row.byte_count=2
        if mutation=='bad-count': row.byte_count=-1
        if mutation=='hash': row.compressed=zlib.compress(b'other');row.byte_count=5
        if mutation=='utf8': row.compressed=zlib.compress(b'\xff');row.byte_count=1
        db.commit()
        damaged=row.compressed
        with pytest.raises(ValueError): store.load_data(db,key)
        with pytest.raises(ValueError): store.put_data(db,data,key,env.admin.id)
        db.rollback()
        assert db.get(m.JudgeTestData,key).compressed==damaged


def test_shared_quota_exact_retries_and_failed_write_rollback(env,monkeypatch):
    monkeypatch.setattr(store.settings,'JUDGE_TEST_DATA_STORE_MAX_MB',1)
    data=b'a'*(1024**2)
    with env.factory() as db:
        store.put_data(db,data,digest(data),env.admin.id);db.commit()
        assert store.put_data(db,data,digest(data),env.admin.id)['replayed']
        with pytest.raises(HTTPException) as exc: store.put_data(db,b'x',digest(b'x'),env.admin.id)
        assert exc.value.status_code==409
        db.rollback()
        assert db.query(m.JudgeTestData).count()==1


def test_cross_session_duplicate_uploads_have_one_row(env):
    data=b'shared\n';ready=Barrier(2)
    def save():
        with env.factory() as db:
            ready.wait(timeout=5)
            result=store.put_data(db,data,digest(data),env.admin.id);db.commit();return result
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:save(),range(2)))
    assert sorted(r['replayed'] for r in results)==[False,True]
    with env.factory() as db: assert db.query(m.JudgeTestData).count()==1


def test_object_count_quota_prevents_unbounded_tiny_rows(env,monkeypatch):
    monkeypatch.setattr(store.settings,'JUDGE_TEST_DATA_STORE_MAX_OBJECTS',1)
    with env.factory() as db:
        store.put_data(db,b'',digest(b''),env.admin.id);db.commit()
        assert store.put_data(db,b'',digest(b''),env.admin.id)['replayed']
        with pytest.raises(HTTPException): store.put_data(db,b'x',digest(b'x'),env.admin.id)
        db.rollback()
        assert db.query(m.JudgeTestData).count()==1


@pytest.mark.asyncio
async def test_admin_upload_and_metadata_never_expose_data_to_public(env):
    data=b'PRIVATE HIDDEN INPUT\n'
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        for user,expected in ((None,401),(env.alice,403)):
            auth=headers(user) if user else {}
            assert (await client.put(url(data),content=data,headers={**auth,'Content-Type':'text/plain'})).status_code==expected
            assert (await client.get(url(data),headers=auth)).status_code==expected
        for replayed in (False,True):
            result=await client.put(url(data),content=data,headers={**headers(env.admin),'Content-Type':'text/plain'})
            assert result.status_code==200,result.text
            assert result.json()['replayed']==replayed and 'PRIVATE' not in result.text
            assert result.headers['cache-control']=='no-store'
        read=await client.get(url(data),headers=headers(env.admin))
        assert read.status_code==200 and set(read.json())=={'digest','byteCount','encoding'}
        assert read.headers['cache-control']=='no-store'
        assert (await client.delete(url(data),headers=headers(env.admin))).status_code==405
    with env.factory() as db:
        assert db.query(m.JudgeTestData).count()==1
        assert db.query(m.Submission).count()==db.query(m.ContestSubmission).count()==0
        events=db.query(m.AdminAuditEvent).all()
        assert events and all('PRIVATE' not in e.action for e in events)


@pytest.mark.asyncio
async def test_declared_cap_headers_digest_and_slot_reject_before_mutation(env):
    data=b'input'
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        auth={**headers(env.admin),'Content-Type':'text/plain'}
        assert (await client.put(url(data),content=data,headers={**auth,'Content-Encoding':'gzip'})).status_code==415
        assert (await client.put(url(data),content=data,headers={**auth,'Content-Length':'1'})).status_code==400
        assert (await client.put(url(data),content=b'wrong',headers=auth)).status_code==422
        assert (await client.put(url(data).replace('byteCount=5',f'byteCount={store.MAX_DATA_BYTES+1}'),content=b'',headers=auth)).status_code==422
        assert routes._upload_slot.acquire(blocking=False)
        try: assert (await client.put(url(data),content=data,headers=auth)).status_code==429
        finally: routes._upload_slot.release()
    with env.factory() as db: assert db.query(m.JudgeTestData).count()==0


@pytest.mark.asyncio
async def test_unauthorized_requests_do_not_consume_a_large_body(env):
    async def never_read():
        raise AssertionError('Unauthorized body consumed')
        yield b''
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        for user,status in ((None,401),(env.alice,403)):
            auth=headers(user) if user else {}
            result=await client.put(url(b'x'),content=never_read(),headers={**auth,'Content-Type':'text/plain'})
            assert result.status_code==status


@pytest.mark.asyncio
async def test_cancelled_save_keeps_slot_and_session_until_thread_finishes(env,monkeypatch):
    entered=Event();release=Event();original=store.put_data
    def save(*args):
        entered.set();assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(store,'put_data',save)
    data=b'cancel-safe'
    async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
        task=asyncio.create_task(client.put(url(data),content=data,
            headers={**headers(env.admin),'Content-Type':'text/plain'}))
        try:
            assert await asyncio.to_thread(entered.wait,3)
            task.cancel();await asyncio.sleep(0.01)
            assert not task.done() and routes._upload_slot.locked()
        finally: release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert not routes._upload_slot.locked()
    with env.factory() as db:
        assert db.query(m.JudgeTestData).count()==1
        assert store.load_data(db,digest(data))==data


def streamed(chunks,delay=0):
    async def stream():
        for chunk in chunks:
            if delay: await asyncio.sleep(delay)
            yield chunk
    return SimpleNamespace(headers=Headers({'content-type':'text/plain'}),stream=stream)


@pytest.mark.asyncio
async def test_streaming_utf8_splits_overruns_timeout_and_cancellation(monkeypatch):
    data='한글'.encode()
    assert await routes.receive_data(streamed([data[:1],data[1:4],data[4:]]),digest(data),len(data))==data
    for chunks,count,code in (([data],1,413),([data[:1]],1,422),([b'x'],2,422)):
        with pytest.raises(HTTPException) as exc:
            await routes.receive_data(streamed(chunks),digest(data),count)
        assert exc.value.status_code==code
    monkeypatch.setattr(routes,'UPLOAD_SECONDS',0.01)
    with pytest.raises(HTTPException) as exc:
        await routes.receive_data(streamed([b'x'],0.1),digest(b'x'),1)
    assert exc.value.status_code==408
    task=asyncio.create_task(routes.receive_data(streamed([b'x'],1),digest(b'x'),1))
    await asyncio.sleep(0);task.cancel()
    with pytest.raises(asyncio.CancelledError): await task


@pytest.mark.asyncio
async def test_extremely_long_content_length_is_rejected_without_integer_conversion():
    request=streamed([b'x'])
    request.headers=Headers({'content-type':'text/plain','content-length':'9'*5000})
    with pytest.raises(HTTPException) as exc:
        await routes.receive_data(request,digest(b'x'),1)
    assert exc.value.status_code==400


def test_v16_additive_repeat_keeps_existing_schema_markers_and_data(env):
    with env.factory() as db:
        data=b'private';store.put_data(db,data,digest(data),env.admin.id);db.commit()
    engine=env.db.get_bind()
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)'))
        connection.execute(text("INSERT INTO schema_migrations (version) VALUES ('20260926_judge_metrics_v15')"))
    initialize(bind=engine,skip_bootstrap=True);initialize(bind=engine,skip_bootstrap=True)
    assert 'judge_test_data' in inspect(engine).get_table_names()
    with env.factory() as db:
        assert store.load_data(db,digest(data))==data
        versions=list(db.execute(text('SELECT version FROM schema_migrations')).scalars())
        assert versions.count(RUNTIME_SCHEMA_VERSION)==1 and versions.count('20260926_judge_metrics_v15')==0
        assert db.execute(text('SELECT 1 FROM runtime_schema_history WHERE version=:v'),
                          {'v':'20260926_judge_metrics_v15'}).first()
