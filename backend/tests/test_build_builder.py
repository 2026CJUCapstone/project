"""Read-only builder proof, including identity drift between build phases."""
from copy import deepcopy
import json

import pytest

from tests.test_build_builder_config import builder, CONTAINER_ID


def runtime():
    return {'Id':CONTAINER_ID,'Name':'/buildx_buildkit_audit0',
        'State':{'Running':True,'Paused':False,'Restarting':False,'Pid':42},
        'HostConfig':{'Memory':512*1024*1024,'MemorySwap':512*1024*1024,
            'CpuPeriod':100000,'CpuQuota':25000,'NanoCpus':0,'PidsLimit':256,
            'PidMode':'','NetworkMode':'bridge'}}


class Docker:
    def __init__(self):
        self.metadata={'Name':'audit','Driver':'docker-container','Dynamic':False,
            'Nodes':[{'Name':'audit0','Status':'running','Endpoint':'unix:///var/run/docker.sock'}]}
        self.container=runtime()
        self.calls=[]
        self.replacement=None

    def __call__(self,args):
        self.calls.append(args)
        if args==['buildx','ls','--format','{{json .}}']:
            return json.dumps(self.metadata)
        assert args[:5]==['--host','unix:///var/run/docker.sock','container','inspect',args[4]]
        assert args[4] in ('buildx_buildkit_audit0',CONTAINER_ID)
        item=deepcopy(self.container)
        if self.replacement and len(self.calls)>2: item['Id']=self.replacement
        return json.dumps([item])


@pytest.fixture(autouse=True)
def host_cgroup(monkeypatch):
    root='/sys/fs/cgroup/system.slice/docker-'+CONTAINER_ID+'.scope'
    files={'/proc/42/cgroup':'0::/system.slice/docker-'+CONTAINER_ID+'.scope/init\n',
        root+'/memory.max':str(512*1024*1024),root+'/memory.swap.max':'0',
        root+'/cpu.max':'25000 100000',root+'/pids.max':'256'}
    monkeypatch.setattr(builder,'read_host_text',lambda path:files[path])


def test_binds_named_builder_to_full_id_without_any_mutation():
    fake=Docker()
    config=builder.Config('audit',512,250,256)
    assert builder.verify(config,fake)==CONTAINER_ID
    assert fake.calls==[['buildx','ls','--format','{{json .}}'],
        ['--host','unix:///var/run/docker.sock','container','inspect','buildx_buildkit_audit0'],
        ['--host','unix:///var/run/docker.sock','container','inspect','buildx_buildkit_audit0']]


def test_identical_buildx_rows_are_one_observation_but_conflicting_rows_fail():
    fake=Docker()
    def duplicate(args):
        result=fake(args)
        return result+'\n'+result if args[0]=='buildx' else result
    assert builder.verify(builder.Config('audit'),duplicate)==CONTAINER_ID
    def conflicting(args):
        result=fake(args)
        if args[0]=='buildx':
            other=deepcopy(fake.metadata)
            other['Nodes'][0]['Endpoint']='tcp://other:2375'
            return result+'\n'+json.dumps(other)
        return result
    with pytest.raises(builder.BuilderError): builder.verify(builder.Config('audit'),conflicting)


@pytest.mark.parametrize('field,value',[
    ('Memory',0),('Memory',1024*1024*1024),('MemorySwap',-1),('MemorySwap',1024*1024*1024),
    ('CpuQuota',0),('CpuQuota',25001),('CpuPeriod',0),('NanoCpus',1000000000),
    ('PidsLimit',None),('PidsLimit',-1),('PidsLimit',257),('PidMode','host'),('NetworkMode','host')])
def test_unbounded_or_excess_resource_configuration_rejected(field,value):
    fake=Docker()
    fake.container['HostConfig'][field]=value
    with pytest.raises(builder.BuilderError): builder.verify(builder.Config('audit',512,250,256),fake)


@pytest.mark.parametrize('mutation',[
    lambda row:row.update(Driver='docker'),lambda row:row.update(Dynamic=True),
    lambda row:row['Nodes'].append(deepcopy(row['Nodes'][0])),
    lambda row:row['Nodes'][0].update(Status='stopped'),
    lambda row:row['Nodes'][0].update(Endpoint='default'),
    lambda row:row['Nodes'][0].update(Endpoint='tcp://remote:2375'),
])
def test_no_implicit_bootstrap_remote_endpoint_or_extra_nodes(mutation):
    fake=Docker()
    mutation(fake.metadata)
    with pytest.raises(builder.BuilderError): builder.verify(builder.Config('audit'),fake)
    assert len(fake.calls)==1


def test_same_named_replacement_cannot_be_adopted_on_later_phase():
    fake=Docker()
    fake.container['Id']='b'*64
    with pytest.raises(builder.BuilderError):
        builder.verify(builder.Config('audit',container_id=CONTAINER_ID),fake)
    assert fake.calls[1][-1]==CONTAINER_ID


def test_name_replaced_during_verification_fails():
    fake=Docker()
    fake.replacement='b'*64
    with pytest.raises(builder.BuilderError): builder.verify(builder.Config('audit'),fake)


@pytest.mark.parametrize('response',['{}','[]','null','{"Name":"audit","Nodes":null}','not-json'])
def test_malformed_metadata_is_closed(response):
    with pytest.raises(builder.BuilderError): builder.verify(builder.Config('audit'),lambda _:response)


def test_host_limit_drift_cannot_hide_behind_docker_metadata(monkeypatch):
    original=builder.read_host_text
    monkeypatch.setattr(builder,'read_host_text',lambda path:'max' if path.endswith('memory.max') else original(path))
    with pytest.raises(builder.BuilderError): builder.verify(builder.Config('audit'),Docker())


def test_daemon_init_subgroup_and_run_sibling_share_bound_container_root():
    root='/system.slice/docker-'+CONTAINER_ID+'.scope'
    assert builder.container_cgroup('0::'+root+'/init\n',CONTAINER_ID)==root
    assert builder.container_cgroup('0::'+root+'/buildkit/step\n',CONTAINER_ID)==root
    with pytest.raises(builder.BuilderError):
        builder.container_cgroup('0::/system.slice/docker-'+'b'*64+'.scope/init\n',CONTAINER_ID)
