"""Exact pool/runtime ownership and bounded, read-only absence evidence."""
from copy import deepcopy
import json

import pytest

from tests.test_edge_deploy import edge
from sandbox_inventory import SandboxInventory


RUNTIME = {'id':'a'*32,'pool_id':'blue','deployment_sha':'b'*40,'sandbox_pool_id':'shared'}
IDENTITY = 'c'*64


def container(runtime=None):
    runtime = runtime or RUNTIME
    return {'Id':IDENTITY,'Config':{'Labels':{
        'webcompiler.pool':runtime['sandbox_pool_id'], 'webcompiler.runtime-version':'1',
        'webcompiler.runtime':runtime['id'],'webcompiler.runtime-pool':runtime['pool_id'],
        'webcompiler.release':runtime['deployment_sha'],'webcompiler.worker':'d'*32,
        'webcompiler.process':'e'*32,'webcompiler.lease':'f'*32,'webcompiler.job':'1'*32,
    }}, 'State':{'Status':'exited'}}


def observer(rows, listings=None):
    calls = []
    rounds = iter(listings) if listings is not None else None
    def call(args):
        calls.append(args)
        if args[:2]==['container','ls']:
            assert args==['container','ls','--all','--no-trunc','--filter',
                'label=webcompiler.pool=shared','--format','{{.ID}}']
            return next(rounds) if rounds is not None else '\n'.join(rows)
        assert args[:2]==['container','inspect'] and len(args)==3
        return json.dumps([rows[args[2]]])
    return SandboxInventory(deepcopy(RUNTIME),call=call),calls


def test_empty_pool_is_observed_twice_without_mutations():
    subject,calls=observer({})
    assert subject.empty() is True
    assert len(calls)==2


@pytest.mark.parametrize('status',['created','running','exited','dead'])
def test_even_exited_runtime_sandbox_prevents_retirement(status):
    item=container()
    item['State']['Status']=status
    subject,calls=observer({IDENTITY:item})
    with pytest.raises(edge.EdgeError,match='containers remain'): subject.empty()
    assert all(args[1] in ('ls','inspect') for args in calls)


@pytest.mark.parametrize('listings',[[IDENTITY,''],['',IDENTITY]])
def test_appearance_or_disappearance_between_reads_is_not_absence(listings):
    subject,_=observer({IDENTITY:container()},listings)
    with pytest.raises(edge.EdgeError,match='containers remain'): subject.empty()


def test_explicit_other_runtime_in_same_sandbox_pool_is_not_retired():
    other={**RUNTIME,'id':'2'*32,'pool_id':'green','deployment_sha':'3'*40}
    subject,calls=observer({IDENTITY:container(other)})
    assert subject.empty() is True
    assert len(calls)==4


@pytest.mark.parametrize('key,value',[
    ('webcompiler.runtime-version',None),('webcompiler.runtime-version','2'),
    ('webcompiler.pool','other'),('webcompiler.runtime','0'*32),
    ('webcompiler.runtime-pool','green'),('webcompiler.release','4'*40),
    ('webcompiler.worker','0'*32),('webcompiler.process',None),
    ('webcompiler.lease','A'*32),('webcompiler.job','0'*32),
    ('webcompiler.job','00000000-0000-0000-0000-000000000000'),
    ('webcompiler.job','bad'),
])
def test_unbound_or_conflicting_ownership_never_becomes_absence(key,value):
    item=container()
    item['Config']['Labels'][key]=value
    subject,_=observer({IDENTITY:item})
    with pytest.raises(edge.EdgeError): subject.empty()


@pytest.mark.parametrize('ids',[IDENTITY+'\n'+IDENTITY,'bad','\n'.join(f'{i+1:064x}' for i in range(257))])
def test_ambiguous_or_oversized_listing_fails_before_inspection(ids):
    subject,calls=observer({},[ids])
    with pytest.raises(edge.EdgeError): subject.empty()
    assert len(calls)==1


@pytest.mark.parametrize('raw',['x'*262145,42,'[{"Id":"wrong"}]','null','[]','[{}]'],
    ids=['oversized','not-text','wrong-id','null','empty','missing-fields'])
def test_malformed_or_oversized_inspect_is_sanitized(raw):
    subject,_=observer({})
    subject.call=lambda args:IDENTITY if args[1]=='ls' else raw
    with pytest.raises(edge.EdgeError): subject.empty()


def test_query_failure_is_not_treated_as_a_disappeared_container():
    subject,_=observer({})
    def call(args):
        if args[1]=='ls': return IDENTITY
        raise edge.EdgeError('owned query failed')
    subject.call=call
    with pytest.raises(edge.EdgeError,match='owned query failed'): subject.empty()


def test_slow_second_read_cannot_prove_absence():
    now=[0]
    calls=[]
    def call(args):
        calls.append(args)
        now[0]+=23
        return ''
    subject=SandboxInventory(deepcopy(RUNTIME),call=call,clock=lambda:now[0])
    with pytest.raises(edge.EdgeError,match='bounded capacity'): subject.empty()
    assert len(calls)==2
