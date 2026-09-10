import copy
from datetime import datetime, timezone, timedelta
import importlib.util
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('image_scan_contract', ROOT/'scripts/scan_image.py')
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)
IMAGE = 'sha256:' + 'a'*64
REF = 'docker.io/library/nginx@sha256:' + 'b'*64
COMMIT = 'c'*40


def report():
    return {'SchemaVersion': 2, 'ArtifactType': 'container_image', 'ArtifactName': IMAGE,
        'Metadata': {'ImageID': IMAGE, 'RepoDigests': [REF],
            'OS': {'Family': 'alpine', 'Name': '3.24.1'},
            'ImageConfig': {'os': 'linux', 'architecture': 'amd64',
                'history': [{'created_by': 'SECRET_SENTINEL'}],
                'config': {'Env': ['PASSWORD=SECRET_SENTINEL'], 'Labels': {'io.webcompiler.source-sha': COMMIT, 'io.webcompiler.image-role': 'frontend'}}}},
        'Results': [{'Target': 'alpine', 'Class': 'os-pkgs', 'Type': 'alpine',
            'Packages': [{'ID': 'musl@1', 'Name': 'musl', 'Version': '1', 'Identifier': {'PURL': 'pkg:apk/alpine/musl@1'}}]}]}


def summarize(value):
    return scan.summarize(value, target=IMAGE, source='docker', scope='application', commit=COMMIT, role='frontend')


def bom(value):
    return {'bomFormat': 'CycloneDX', 'metadata': {'component': {'type': 'container',
        'name': value['ArtifactName'], 'properties': [{'name': 'aquasecurity:trivy:ImageID', 'value': IMAGE}]}},
        'components': [{'type': 'library', 'purl': p['Identifier']['PURL'], 'version': p['Version']}
            for result in value['Results'] for p in result['Packages']]}


def test_redacts_environment_and_build_history_but_retains_inventory():
    value = report()
    before = copy.deepcopy(value)
    safe, summary = summarize(value)
    assert value == before
    assert 'SECRET_SENTINEL' not in json.dumps(safe)
    assert safe['Results'] == value['Results']
    assert summary['sourceCommit'] == COMMIT and summary['policyPassed']


@pytest.mark.parametrize('kind', ['id', 'source', 'artifact', 'os', 'platform', 'empty', 'partial', 'missing-version', 'class', 'schema'])
def test_rejects_mismatched_or_incomplete_image_evidence(kind):
    value = report()
    if kind == 'id': value['Metadata']['ImageID'] = 'sha256:'+'d'*64
    elif kind == 'source': value['Metadata']['ImageConfig']['config']['Labels']['io.webcompiler.source-sha'] = 'd'*40
    elif kind == 'artifact': value['ArtifactName'] = 'mutable:latest'
    elif kind == 'os': value['Metadata']['OS'] = {}
    elif kind == 'platform': value['Metadata']['ImageConfig']['architecture'] = 'arm64'
    elif kind == 'empty': value['Results'] = []
    elif kind == 'partial': value['Results'][0].pop('Packages')
    elif kind == 'missing-version': value['Results'][0]['Packages'][0].pop('Version')
    elif kind == 'class': value['Results'][0]['Class'] = 'config'
    elif kind == 'schema': value['SchemaVersion'] = 1
    with pytest.raises(scan.ScanError): summarize(value)


@pytest.mark.parametrize('severity,passed', [('UNKNOWN', False), ('HIGH', False), ('CRITICAL', False), ('LOW', True), ('MEDIUM', True)])
def test_policy_does_not_ignore_unfixed_or_unknown_findings(severity, passed):
    value = report()
    value['Results'][0]['Vulnerabilities'] = [{'VulnerabilityID': 'CVE-fixture', 'Severity': severity, 'FixedVersion': ''}]
    _, summary = summarize(value)
    assert summary['policyPassed'] is passed
    assert summary['findingEntriesBySeverity'] == {severity: 1}


def test_eol_and_malformed_severity_are_not_success():
    value = report()
    value['Metadata']['OS']['EOSL'] = True
    assert summarize(value)[1]['policyPassed'] is False
    value['Results'][0]['Vulnerabilities'] = [{'VulnerabilityID': 'fixture', 'Severity': 'MAYBE'}]
    with pytest.raises(scan.ScanError): summarize(value)


def test_remote_digest_must_match_and_cannot_claim_source_commit():
    value = report()
    value['ArtifactName'] = REF
    assert scan.summarize(value, target=REF, source='remote', scope='base')[1]['sourceCommit'] is None
    value['Metadata']['RepoDigests'] = []
    with pytest.raises(scan.ScanError): scan.summarize(value, target=REF, source='remote', scope='base')
    with pytest.raises(scan.ScanError): scan.validate_target(REF, 'remote', 'application', COMMIT)


@pytest.mark.parametrize('failure', [None, 'scanner', 'version', 'stale-db', 'convert', 'empty-sbom'])
def test_orchestration_fail_closed_and_filters_caller_configuration(tmp_path, monkeypatch, failure):
    tool = tmp_path/'trivy'
    tool.write_bytes(b'test binary')
    cache = tmp_path/'cache'
    (cache/'db').mkdir(parents=True)
    updated = datetime.now(timezone.utc) - timedelta(hours=72 if failure == 'stale-db' else 1)
    (cache/'db/metadata.json').write_text(json.dumps({'Version': 2, 'UpdatedAt': updated.isoformat()}))
    output = tmp_path/'evidence'
    monkeypatch.setenv('TRIVY_SKIP_DB_UPDATE', 'true')
    monkeypatch.setenv('TRIVY_IGNORE_UNFIXED', 'true')
    monkeypatch.setenv('TRIVY_SEVERITY', 'LOW')
    seen = []
    def command(args, **kwargs):
        seen.append(args)
        assert not {'TRIVY_SKIP_DB_UPDATE', 'TRIVY_IGNORE_UNFIXED', 'TRIVY_SEVERITY'} & kwargs['env'].keys()
        assert kwargs['cwd'] != ROOT
        if args[1] == 'version':
            return subprocess.CompletedProcess(args, 0, json.dumps({'Version': 'old' if failure == 'version' else scan.VERSION}))
        assert json.loads(Path(args[args.index('--config')+1]).read_text()) == {}
        path = Path(args[args.index('--output')+1])
        if args[1] == 'image':
            assert args[args.index('--image-src')+1] == 'docker'
            assert args[-1] == IMAGE and '--ignore-unfixed=false' in args
            assert Path(args[args.index('--ignorefile')+1]).read_text() == ''
            path.write_text(json.dumps(report()))
            return subprocess.CompletedProcess(args, 1 if failure == 'scanner' else 0)
        assert 'SECRET_SENTINEL' not in Path(args[-1]).read_text()
        inventory = bom(report())
        if failure == 'empty-sbom': inventory['components'] = []
        path.write_text(json.dumps(inventory))
        return subprocess.CompletedProcess(args, 1 if failure == 'convert' else 0)
    with patch.object(scan.subprocess, 'run', side_effect=command):
        kwargs = dict(trivy=tool, target=IMAGE, source='docker', scope='application', commit=COMMIT, output=output, cache=cache, role='frontend')
        if failure:
            with pytest.raises(scan.ScanError): scan.run_scan(**kwargs)
            assert not output.exists()
        else:
            result = scan.run_scan(**kwargs)
            assert result['policyPassed'] and (output/'manifest.json').is_file()
            assert 'SECRET_SENTINEL' not in (output/'report.json').read_text()
            count = len(seen)
            with pytest.raises(scan.ScanError): scan.run_scan(**kwargs)
            assert len(seen) == count


def test_read_budget(tmp_path):
    path = tmp_path/'large.json'
    path.write_bytes(b' ' * (scan.LIMIT + 1))
    with pytest.raises(scan.ScanError): scan.read_json(path)


@pytest.mark.parametrize('role,purl', [('backend', 'pkg:pypi/fastapi@1'), ('sandbox', 'pkg:npm/npm@1')])
def test_application_requires_role_binding_and_detected_library_inventory(role, purl):
    value = report()
    args = dict(target=IMAGE, source='docker', scope='application', commit=COMMIT, role=role)
    with pytest.raises(scan.ScanError, match='role'): scan.summarize(value, **args)
    value['Metadata']['ImageConfig']['config']['Labels']['io.webcompiler.image-role'] = role
    with pytest.raises(scan.ScanError, match='library inventory'): scan.summarize(value, **args)
    value['Results'].append({'Class': 'lang-pkgs', 'Packages': [
        {'Name': 'fixture', 'Version': '1', 'Identifier': {'PURL': purl}}]})
    assert scan.summarize(value, **args)[1]['role'] == role


@pytest.mark.parametrize('kind', ['missing', 'unexpected', 'wrong-version', 'no-purl', 'wrong-image', 'raw-no-purl'])
def test_converted_sbom_must_retain_exact_detected_inventory(kind):
    value = report()
    value['Results'][0]['Packages'].append({'Name': 'other', 'Version': '2', 'Identifier': {'PURL': 'pkg:apk/alpine/other@2'}})
    inventory = bom(value)
    if kind == 'missing': inventory['components'].pop()
    if kind == 'unexpected': inventory['components'][0]['purl'] = 'pkg:apk/alpine/injected@1'
    if kind == 'wrong-version': inventory['components'][0]['version'] = 'wrong'
    if kind == 'no-purl': inventory['components'][0].pop('purl')
    if kind == 'wrong-image': inventory['metadata']['component']['properties'][0]['value'] = 'sha256:'+'f'*64
    if kind == 'raw-no-purl': value['Results'][0]['Packages'][0].pop('Identifier')
    with pytest.raises(scan.ScanError): scan.verify_inventory(value, inventory)


def test_inventory_coalesces_duplicate_purls_and_checks_encoded_epoch():
    value = report()
    package = value['Results'][0]['Packages'][0]
    package['Identifier']['PURL'] = 'pkg:deb/ubuntu/pkg@1%3A2-3?arch=amd64'
    package['Version'] = '1:2-3'
    inventory = bom(value)
    value['Results'][0]['Packages'].append(copy.deepcopy(package))
    assert scan.verify_inventory(value, inventory) == 1
