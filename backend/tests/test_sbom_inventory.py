"""Lock-inventory fidelity, not a CycloneDX schema or CVE scanner test."""
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'verify_sbom.py'
spec = importlib.util.spec_from_file_location('audit_sbom_inventory', SCRIPT)
sbom = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sbom)
COMMIT = '1' * 40


def encoded(value):
    return json.dumps(value).encode()


def npm_lock():
    return {'lockfileVersion': 3, 'packages': {
        '': {'name': 'app', 'version': '1.0.0'},
        'node_modules/@example/core': {'version': '2.0.0'},
        'node_modules/tool': {'version': '3.0.0', 'dev': True},
        'node_modules/tool/node_modules/@example/core': {'version': '2.0.0'},
        'node_modules/other/node_modules/tool': {'version': '4.0.0', 'optional': True},
    }}


def inventory():
    packages = [('@example/core', '2.0.0'), ('tool', '3.0.0'), ('tool', '4.0.0')]
    return {'bomFormat': 'CycloneDX', 'specVersion': '1.5',
        'metadata': {'component': {'type': 'application', 'bom-ref': 'root'}},
        'components': [{'type': 'library', 'name': name, 'version': version,
            'bom-ref': str(i)} for i, (name, version) in enumerate(packages)],
        'dependencies': [{'ref': 'root', 'dependsOn': ['0', '1']},
            {'ref': '0', 'dependsOn': []}, {'ref': '1', 'dependsOn': ['2']},
            {'ref': '2', 'dependsOn': []}]}


def check(bom=None, lock=None):
    return sbom.verify(encoded(npm_lock() if lock is None else lock),
        encoded(inventory() if bom is None else bom), 'npm', COMMIT)


def test_scoped_nested_dev_optional_and_multiple_versions_are_preserved():
    result = check()
    assert result == {'schemaVersion': 1, 'sourceCommit': COMMIT, 'ecosystem': 'npm',
        'inventoryScope': 'source-lockfile-not-installed-image',
        'lockfileSha256': hashlib.sha256(encoded(npm_lock())).hexdigest(),
        'sbomSha256': hashlib.sha256(encoded(inventory())).hexdigest(),
        'componentCount': 3, 'uniquePackageVersions': 3, 'cycloneDxVersion': '1.5'}


@pytest.mark.parametrize('index', [0, 1, 2])
@pytest.mark.parametrize('mutation', ['missing', 'version', 'name'])
def test_each_missing_or_changed_package_is_rejected(index, mutation):
    bom = inventory()
    if mutation == 'missing':
        bom['components'].pop(index)
    else:
        bom['components'][index][mutation] = 'incorrect'
    with pytest.raises(sbom.SBOMError, match='do not match'):
        check(bom)


def test_additional_package_is_not_a_valid_inventory():
    bom = inventory()
    bom['components'].append({'name': 'extra', 'version': '1', 'type': 'library', 'bom-ref': 'extra'})
    with pytest.raises(sbom.SBOMError, match='do not match'):
        check(bom)


def test_npm_alias_uses_locked_package_name_not_installation_alias():
    lock = npm_lock()
    lock['packages']['node_modules/alias'] = {'name': '@example/core', 'version': '2.0.0'}
    assert check(lock=lock)['uniquePackageVersions'] == 3


def test_repeated_installations_can_have_distinct_references():
    bom = inventory()
    duplicate = deepcopy(bom['components'][0])
    duplicate['bom-ref'] = 'separate-installation'
    bom['components'].append(duplicate)
    result = check(bom)
    assert result['componentCount'] == 4
    assert result['uniquePackageVersions'] == 3


def test_actual_npm10_duplicate_reference_failure_is_not_hidden_by_set_equality():
    bom = inventory()
    bom['components'].append(deepcopy(bom['components'][0]))
    with pytest.raises(sbom.SBOMError, match='duplicate'):
        check(bom)


@pytest.mark.parametrize('field,value', [
    ('type', 'application'), ('name', ''), ('name', None), ('version', ''),
    ('version', None), ('bom-ref', ''), ('bom-ref', None), ('bom-ref', []),
    ('components', [{'name': 'hidden-child'}]),
])
def test_invalid_component_rejected(field, value):
    bom = inventory()
    bom['components'][0][field] = value
    with pytest.raises(sbom.SBOMError):
        check(bom)


@pytest.mark.parametrize('graph', [None, {}, [None], [{'ref': 'unknown'}],
    [{'ref': '0'}, {'ref': '0'}], [{'ref': '0', 'dependsOn': '1'}],
    [{'ref': '0', 'dependsOn': ['unknown']}], [{'ref': '0', 'dependsOn': [None]}]])
def test_invalid_and_dangling_dependency_references_rejected(graph):
    bom = inventory()
    bom['dependencies'] = graph
    with pytest.raises(sbom.SBOMError):
        check(bom)


def test_application_reference_cannot_shadow_library():
    bom = inventory()
    bom['metadata']['component']['bom-ref'] = '0'
    with pytest.raises(sbom.SBOMError, match='collide'):
        check(bom)


@pytest.mark.parametrize('field,value', [
    ('bomFormat', 'SPDX'), ('specVersion', None), ('specVersion', 'invalid'),
    ('components', []), ('components', {}),
])
def test_inventory_envelope_rejected(field, value):
    bom = inventory()
    bom[field] = value
    with pytest.raises(sbom.SBOMError):
        check(bom)


@pytest.mark.parametrize('entry', [None, {'link': True, 'version': '1'}, {},
    {'version': None}, {'version': 1}])
def test_unsupported_npm_lock_entries_fail(entry):
    lock = npm_lock()
    lock['packages']['node_modules/additional'] = entry
    with pytest.raises(sbom.SBOMError):
        check(lock=lock)


@pytest.mark.parametrize('raw', [b'{}', b'{"lockfileVersion":2,"packages":{}}',
    b'{"lockfileVersion":3,"packages":[]}', b'{"lockfileVersion":3,"packages":{}}'])
def test_missing_or_wrong_npm_lock_inventory_fails(raw):
    with pytest.raises(sbom.SBOMError):
        sbom.expected_packages(raw, 'npm')


def test_python_normalization_extras_hashes_comments_and_lock_byte_binding():
    lock = ('# generated\nSome_Project[feature]==1.2.3 \\\n'
        '    --hash=sha256:' + 'a' * 64 + '\n# via root\nother.pkg==2.0\n').encode()
    bom = {'bomFormat': 'CycloneDX', 'specVersion': '1.4', 'components': [
        {'type': 'library', 'name': 'some-project', 'version': '1.2.3', 'bom-ref': 'a'},
        {'type': 'library', 'name': 'Other_Pkg', 'version': '2.0', 'bom-ref': 'b'}]}
    result = sbom.verify(lock, encoded(bom), 'pypi', COMMIT)
    assert result['uniquePackageVersions'] == 2
    # Same package set with a different source hash must not reuse the manifest hash.
    changed = sbom.verify(lock + b'# another source byte\n', encoded(bom), 'pypi', COMMIT)
    assert changed['lockfileSha256'] != result['lockfileSha256']


@pytest.mark.parametrize('raw', [b'', b'# only comment\n', b'foo>=1', b'-r other.txt',
    b'foo==1; python_version<"3.12"', b'foo @ https://example.invalid/foo.whl',
    b'--index-url https://example.invalid', b'foo==1\n--hash=md5:abc'])
def test_unsupported_python_requirements_fail_instead_of_silently_omitting(raw):
    with pytest.raises(sbom.SBOMError):
        sbom.expected_packages(raw, 'pypi')


@pytest.mark.parametrize('commit', ['', 'main', 'a' * 39, 'a' * 41, 'A' * 40, None])
def test_exact_commit_syntax_required(commit):
    with pytest.raises(sbom.SBOMError):
        sbom.verify(encoded(npm_lock()), encoded(inventory()), 'npm', commit)


def test_bounded_reader_rejects_large_stdin(monkeypatch):
    monkeypatch.setattr(sbom.sys, 'stdin', type('Input', (), {
        'buffer': io.BytesIO(b'x' * (32 * 1024 * 1024 + 1))})())
    with pytest.raises(sbom.SBOMError, match='budget'):
        sbom.read_bounded('-')
