"""Read-only, opt-in public manifest verification; never pulls image layers."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest


LOCK = json.loads((Path(__file__).resolve().parents[2] / 'runtime/image-lock.json').read_text())
ACCEPT = ', '.join(['application/vnd.oci.image.index.v1+json',
    'application/vnd.docker.distribution.manifest.list.v2+json',
    'application/vnd.oci.image.manifest.v1+json',
    'application/vnd.docker.distribution.manifest.v2+json'])


def manifest(response, expected, *, require_header=True):
    raw = response.read(2 * 1024 * 1024 + 1)
    assert len(raw) <= 2 * 1024 * 1024, 'Registry manifest exceeds read budget'
    digest = 'sha256:' + hashlib.sha256(raw).hexdigest()
    assert digest == expected, 'Raw registry content does not match locked digest'
    if require_header:
        assert response.headers['Docker-Content-Digest'] == digest, 'Registry digest header mismatch'
    return json.loads(raw)


@pytest.mark.skipif(os.getenv('RUN_IMAGE_REGISTRY_INTEGRATION') != '1',
    reason='explicit public registry manifest integration opt-in required')
@pytest.mark.parametrize('name', sorted(LOCK['images']))
def test_locked_index_and_linux_amd64_manifest_exist_with_exact_bytes(name):
    image = LOCK['images'][name]
    assert LOCK['registry'] == 'https://registry-1.docker.io'
    repository = image['repository']
    query = urlencode({'service': 'registry.docker.io', 'scope': 'repository:' + repository + ':pull'})
    with urlopen('https://auth.docker.io/token?' + query, timeout=15) as response:
        token = json.loads(response.read(65536))['token']
    # Ephemeral anonymous public-pull token is never printed or saved.
    headers = {'Authorization': 'Bearer ' + token, 'Accept': ACCEPT}
    base = LOCK['registry'] + '/v2/' + repository + '/manifests/'
    with urlopen(Request(base + image['digest'], headers=headers), timeout=15) as response:
        index = manifest(response, image['digest'])
    assert index['schemaVersion'] == 2
    children = [item for item in index['manifests']
        if item.get('platform', {}).get('os') == 'linux'
        and item.get('platform', {}).get('architecture') == 'amd64']
    assert len(children) == 1
    assert children[0]['digest'] == image['linuxAmd64']
    with urlopen(Request(base + image['linuxAmd64'], headers=headers), timeout=15) as response:
        child = manifest(response, image['linuxAmd64'])
    assert child['schemaVersion'] == 2
    assert child['config']['digest'].startswith('sha256:')
    assert child['layers']
    if 'nodeVersion' in image:
        # Pin Node build/CI/runtime to the version in the immutable image config,
        # not merely to the mutable human-readable tag or a guessed version.
        config_digest = child['config']['digest']
        config_url = LOCK['registry'] + '/v2/' + repository + '/blobs/' + config_digest
        with urlopen(Request(config_url, headers=headers), timeout=15) as response:
            config = manifest(response, config_digest, require_header=False)
        assert config['architecture'] == 'amd64' and config['os'] == 'linux'
        assert 'NODE_VERSION=' + image['nodeVersion'] in config['config']['Env']
    # Layers, executable behavior and image startup remain outside this test.


@pytest.mark.parametrize('failure', ['body', 'header', 'size'])
def test_registry_evidence_rejects_mismatch_or_oversize(failure):
    from io import BytesIO
    raw = b'{"schemaVersion":2}'
    expected = 'sha256:' + hashlib.sha256(raw).hexdigest()
    if failure == 'body':
        raw += b' '
    elif failure == 'size':
        raw = b'x' * (2 * 1024 * 1024 + 1)
    response = BytesIO(raw)
    response.headers = {'Docker-Content-Digest': 'wrong' if failure == 'header' else expected}
    with pytest.raises(AssertionError):
        manifest(response, expected)
