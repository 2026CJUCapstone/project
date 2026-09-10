"""Explicit preservation is not managed ownership or retirement authority."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from tests.test_runtime_inventory import inventory, LABEL, container_set
from tests.test_runtime_retirement import exited
from tests.test_edge_deploy import edge, adapter


def add_legacy(inventory,role='postgres'):
    deploy,release,subject,containers,networks,calls=inventory
    identity=('e' if role=='postgres' else 'f')*64
    item=deepcopy(next(iter(containers.values())))
    item['Id']=identity
    item['Config'].update(Hostname='legacy-'+role,Labels={
        'com.docker.compose.project':subject.project,'com.docker.compose.service':role},
        Env=['LEGACY_PASSWORD=do-not-record-this-value'])
    item['HostConfig']['NetworkMode']=subject.project+'_default'
    item['NetworkSettings']['Networks']={subject.project+'_default':{'NetworkID':'a'*64}}
    item['Mounts']=[{'Type':'volume','Name':'legacy-data','Destination':'/var/lib/data','RW':True}]
    containers[identity]=item
    return identity,item


def approve(inventory,*identities):
    deploy,release,*_=inventory
    deploy.config=replace(deploy.config,preserved_blue=tuple(identities))
    deploy.bind_preserved()
    inventory[5].clear()
    return deploy.inventory(release)


def test_legacy_stateful_blocks_default_inventory_but_exact_approved_ids_are_preserved(inventory):
    deploy,release,subject,containers,networks,calls=inventory
    first,postgres=add_legacy(inventory)
    second,redis=add_legacy(inventory,'redis')
    original=deepcopy(containers)
    with pytest.raises(edge.EdgeError,match='Foreign or unbound'): subject.capture()
    assert not subject.path.exists()
    subject=approve(inventory,first,second)
    assert subject.capture() and subject.verify()
    raw=subject.path.read_bytes()
    saved=json.loads(raw)
    assert {r['id'] for r in saved['containers']}==set(containers)-{first,second}
    assert {r['id'] for r in saved['preserved_stateful']}=={first,second}
    assert b'do-not-record-this-value' not in raw and b'LEGACY_PASSWORD' not in raw
    assert containers==original
    assert all(c[:2] in (['container','inspect'],['container','ls'],['network','inspect']) for c in calls)


@pytest.mark.parametrize('case',['managed','wrong-project','unknown-role','private-plane','host-network','shared-namespace','missing'])
def test_approved_id_cannot_hide_foreign_or_managed_services(inventory,case):
    identity,item=add_legacy(inventory)
    subject=approve(inventory,identity)
    if case=='managed': item['Config']['Labels'][LABEL+'id']='1'*32
    elif case=='wrong-project': item['Config']['Labels']['com.docker.compose.project']='another-project'
    elif case=='unknown-role': item['Config']['Labels']['com.docker.compose.service']='backend'
    elif case=='private-plane': item['NetworkSettings']['Networks'][subject.project+'-api-plane']={'NetworkID':'b'*64}
    elif case=='host-network': item['HostConfig']['NetworkMode']='host'
    elif case=='shared-namespace': item['HostConfig']['NetworkMode']='container:'+'1'*64
    else: inventory[3].pop(identity)
    with pytest.raises(edge.EdgeError): subject.capture()
    assert not subject.path.exists()


def test_preserved_id_never_becomes_a_stop_target_and_configuration_drift_is_refused(inventory):
    identity,item=add_legacy(inventory)
    subject=approve(inventory,identity)
    assert subject.capture()
    original=subject.path.read_bytes()
    with pytest.raises(edge.EdgeError,match='cannot be retirement'): subject.verify_retiring({identity})
    item['Config']['Env'].append('CHANGED=yes')
    with pytest.raises(edge.EdgeError,match='preservation configuration'): subject.verify()
    assert subject.path.read_bytes()==original


def test_retirement_inventory_excludes_and_preserves_legacy_stateful(inventory):
    deploy,release,_,containers,networks,calls=inventory
    identity,item=add_legacy(inventory)
    before=deepcopy(item)
    subject=approve(inventory,identity)
    assert subject.capture()
    original=subject.path.read_bytes()
    requested=set()
    for managed_id,row in list(containers.items()):
        if managed_id==identity or row['Config']['Labels'][LABEL+'role'] in ('initialize','proxy-control-init'):
            continue
        requested.add(managed_id)
        exited(managed_id,containers,networks)
        assert subject.verify_retiring(requested)==requested
    assert len(requested)==7 and identity not in requested
    assert item==before and subject.path.read_bytes()==original


def test_legacy_mount_order_is_not_configuration_drift(inventory):
    identity,item=add_legacy(inventory)
    item['Mounts'].append({'Type':'volume','Name':'legacy-wal','Destination':'/var/lib/wal','RW':True})
    subject=approve(inventory,identity)
    assert subject.capture()
    item['Mounts'].reverse()
    assert subject.verify()


def test_preservation_preflight_rejects_before_edge_or_database_effects(inventory,monkeypatch):
    identity,item=add_legacy(inventory)
    approve(inventory,identity)
    deploy=inventory[0]
    item['Config']['Labels']['com.docker.compose.service']='worker'
    monkeypatch.setattr(deploy.runtime,'preflight',lambda:pytest.fail('must reject before runtime access'))
    with pytest.raises(edge.EdgeError,match='isolated legacy'): deploy.preflight()
    assert inventory[5]==[['container','inspect',identity]]


def test_preservation_preflight_cannot_rebaseline_changed_config(inventory,monkeypatch):
    identity,item=add_legacy(inventory)
    subject=approve(inventory,identity)
    assert subject.capture()
    item['HostConfig']['Memory']=128*1024*1024
    deploy=inventory[0]
    original=deploy.call
    deploy.call=lambda args: '' if args[:2]==['container','ls'] else original(args)
    monkeypatch.setattr(deploy.runtime,'preflight',lambda:None)
    with pytest.raises(edge.EdgeError,match='preservation configuration'):
        deploy.preflight()


def test_capture_requires_prior_preservation_binding(inventory):
    identity,item=add_legacy(inventory)
    deploy,release=inventory[:2]
    deploy.config=replace(deploy.config,preserved_blue=(identity,))
    subject=deploy.inventory(release)
    with pytest.raises(edge.EdgeError,match='bound before capture'): subject.capture()
    assert not subject.path.exists()
    assert not adapter.preservation_path(deploy.store,subject.project).exists()


@pytest.mark.parametrize('change',['memory','endpoint','alias','omitted-id','replacement-id'])
def test_cross_release_binding_rejects_config_or_selection_change(inventory,change):
    identity,item=add_legacy(inventory)
    subject=approve(inventory,identity)
    deploy=inventory[0]
    path=adapter.preservation_path(deploy.store,subject.project)
    before=path.read_bytes()
    if change=='memory': item['HostConfig']['Memory']=134217728
    elif change=='endpoint': item['NetworkSettings']['Networks'][subject.project+'_default']['EndpointID']='a'*64
    elif change=='alias': item['NetworkSettings']['Networks'][subject.project+'_default']['Aliases']=['replacement-db']
    elif change=='omitted-id': deploy.config=replace(deploy.config,preserved_blue=())
    else:
        replacement,_=add_legacy(inventory,'redis')
        deploy.config=replace(deploy.config,preserved_blue=(replacement,))
    with pytest.raises(edge.EdgeError,match='preservation configuration'): deploy.bind_preserved()
    assert path.read_bytes()==before
    # Different runtime ID cannot make a changed preserved config acceptable.
    next_release=deploy.config.release('blue','b'*40)
    newer=deploy.inventory(next_release)
    legacy_rows={key:value for key,value in inventory[3].items()
        if value['Config']['Labels'].get('com.docker.compose.service') in ('postgres','redis')}
    replacement_containers,replacement_networks=container_set(deploy.config.root,newer.project,next_release,
        shared_network=deploy.config.shared_network)
    inventory[3].clear()
    inventory[3].update(replacement_containers|legacy_rows)
    inventory[4].clear()
    inventory[4].update(replacement_networks)
    with pytest.raises(edge.EdgeError): newer.capture()
    assert not newer.path.exists() and path.read_bytes()==before


def test_prepare_rechecks_preflight_observation_before_launch(inventory,monkeypatch):
    identity,item=add_legacy(inventory)
    deploy=inventory[0]
    deploy.config=replace(deploy.config,preserved_blue=(identity,))
    def preflight():
        deploy._preserved_preflight=deploy.observe_preserved()
        item['HostConfig']['Memory']=134217728
        return None
    monkeypatch.setattr(deploy,'preflight',preflight)
    monkeypatch.setattr(deploy.runtime,'launch_committed',lambda:pytest.fail('launch before stable binding'))
    with pytest.raises(edge.EdgeError,match='changed after preflight'): deploy.prepare()
    assert not adapter.preservation_path(deploy.store,deploy.config.project_prefix+'-blue').exists()


def test_prepare_persists_baseline_before_launch_and_retry_cannot_overwrite(inventory,monkeypatch):
    identity,item=add_legacy(inventory)
    deploy=inventory[0]
    deploy.config=replace(deploy.config,preserved_blue=(identity,))
    def preflight():
        deploy._preserved_preflight=deploy.observe_preserved()
        return None
    monkeypatch.setattr(deploy,'preflight',preflight)
    path=adapter.preservation_path(deploy.store,deploy.config.project_prefix+'-blue')
    def interrupted():
        assert path.is_file() and b'do-not-record-this-value' not in path.read_bytes()
        raise RuntimeError('interrupted runtime launch')
    monkeypatch.setattr(deploy.runtime,'launch_committed',interrupted)
    with pytest.raises(RuntimeError,match='interrupted runtime launch'): deploy.prepare()
    original=path.read_bytes()
    item['HostConfig']['Memory']=134217728
    with pytest.raises(edge.EdgeError,match='preservation configuration'): deploy.prepare()
    assert path.read_bytes()==original


def test_prepare_binds_empty_selection_and_later_addition_needs_reconciliation(inventory,monkeypatch):
    deploy=inventory[0]
    monkeypatch.setattr(deploy,'preflight',lambda:None)
    path=adapter.preservation_path(deploy.store,deploy.config.project_prefix+'-blue')
    def stop_after_binding():
        assert json.loads(path.read_bytes())=={'version':1,'projects':{
            deploy.config.project_prefix+'-blue':[],deploy.config.project_prefix+'-green':[]}}
        raise RuntimeError('fixture stops before launch')
    monkeypatch.setattr(deploy.runtime,'launch_committed',stop_after_binding)
    with pytest.raises(RuntimeError,match='fixture stops'): deploy.prepare()
    before=path.read_bytes()
    identity,_=add_legacy(inventory)
    deploy.config=replace(deploy.config,preserved_blue=(identity,))
    with pytest.raises(edge.EdgeError,match='preservation configuration'): deploy.prepare()
    with pytest.raises(edge.EdgeError,match='preservation configuration'): deploy.observe_preserved()
    assert path.read_bytes()==before


def test_selection_manifest_is_atomic_across_colors_on_write_interruption(inventory,monkeypatch):
    deploy=inventory[0]
    blue_id,_=add_legacy(inventory)
    deploy.config=replace(deploy.config,preserved_blue=(blue_id,))
    path=adapter.preservation_path(deploy.store,deploy.config.project_prefix+'-blue')
    original=deploy.store.write
    writes=[]
    def interrupted(target,value):
        original(target,value)
        writes.append(target)
        raise RuntimeError('interrupted after atomic manifest')
    monkeypatch.setattr(deploy.store,'write',interrupted)
    with pytest.raises(RuntimeError,match='atomic manifest'): deploy.bind_preserved()
    assert writes==[path]
    record=json.loads(path.read_bytes())
    assert set(record['projects'])=={'webcompiler-blue','webcompiler-green'}
    assert record['projects']['webcompiler-green']==[]
    before=path.read_bytes()
    green_id,item=add_legacy(inventory,'redis')
    item['Config']['Labels']['com.docker.compose.project']='webcompiler-green'
    deploy.config=replace(deploy.config,preserved_green=(green_id,))
    with pytest.raises(edge.EdgeError,match='preservation configuration'): deploy.bind_preserved()
    assert path.read_bytes()==before and writes==[path]
