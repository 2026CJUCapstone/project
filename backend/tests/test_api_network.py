from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest


spec = importlib.util.spec_from_file_location('api_network',Path(__file__).resolve().parents[2]/'scripts/ensure_api_network.py')
network = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = network
spec.loader.exec_module(network)


def fixture(tmp_path):
    config = network.Config(str(tmp_path),'audit-blue')
    info = dict(Name=config.name,Driver='bridge',Scope='local',Internal=True,EnableIPv6=False,
                IPAM={'Driver':'default','Config':[{'Subnet':'172.28.0.0/24'}]},Labels=config.labels,
                Containers={})
    return config, info


def test_create_and_repeat_reuse_derives_cidr_without_deleting_or_reconnecting(tmp_path):
    config, info = fixture(tmp_path)
    calls = []
    exists = False
    def call(args):
        nonlocal exists
        calls.append(args)
        if args[:2] == ['network','ls']:
            return config.name if exists else ''
        if args[:2] == ['network','create']:
            exists = True
            assert '--internal' in args
            for key,value in config.labels.items():
                assert key+'='+value in args
            return 'new-network-id'
        assert args == ['network','inspect',config.name]
        return json.dumps([info])
    assert network.ensure(config,call=call) == '172.28.0.0/24'
    assert network.ensure(config,call=call) == '172.28.0.0/24'
    assert sum(args[:2] == ['network','create'] for args in calls) == 1


@pytest.mark.parametrize('change',[
    {'Labels':{}}, {'Name':'foreign'}, {'Driver':'host'}, {'Scope':'swarm'}, {'Internal':False},
    {'EnableIPv6':True}, {'Options':{'com.docker.network.bridge.name':'foreign'}},
    {'IPAM':{'Driver':'default','Config':[{'Subnet':'0.0.0.0/0'}]}},
    {'IPAM':{'Driver':'default','Config':[{'Subnet':'172.16.0.0/12'}]}},
    {'IPAM':{'Driver':'default','Config':[{'Subnet':'127.0.0.0/24'}]}},
    {'IPAM':{'Driver':'default','Config':[{'Subnet':'2001:db8::/64'}]}},
    {'IPAM':{'Driver':'default','Config':[]}},
])
def test_refuse_foreign_network_or_unbounded_nonprivate_subnet_without_mutation(tmp_path,change):
    config, info = fixture(tmp_path)
    info.update(deepcopy(change))
    def call(args):
        assert args[:2] in (['network','ls'],['network','inspect'])
        return config.name if args[1]=='ls' else json.dumps([info])
    with pytest.raises((network.NetworkError,ValueError)):
        network.ensure(config,call=call)


@pytest.mark.parametrize('project,service,valid',[
    ('audit-blue','backend',True),('audit-blue','api-proxy',True),
    ('audit-green','backend',False),('audit-blue','worker',False),('audit-blue','frontend',False),
])
def test_existing_endpoint_roles_and_pool_are_validated(tmp_path,project,service,valid):
    config, info = fixture(tmp_path)
    info['Containers']={'fixture-id':{}}
    def call(args):
        if args[:2]==['network','ls']:
            return config.name
        if args[:2]==['network','inspect']:
            return json.dumps([info])
        assert args==['container','inspect','fixture-id']
        return json.dumps([{'Config':{'Labels':{'com.docker.compose.project':project,
                                              'com.docker.compose.service':service}}}])
    if valid:
        assert network.ensure(config,call=call)=='172.28.0.0/24'
    else:
        with pytest.raises(network.NetworkError):
            network.ensure(config,call=call)
