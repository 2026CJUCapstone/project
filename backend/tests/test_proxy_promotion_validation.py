import pytest

from app.proxy_promotion import candidate, validate_identity


RELEASE = 'a' * 40
POOL_ID = 'blue_pool-1'
GENERATION = 'b' * 32


def valid_status(**overrides):
    status = {
        'deploymentSha': RELEASE,
        'poolId': POOL_ID,
        'available': True,
        'deploymentReady': True,
        'draining': False,
        'readyPeers': 2,
        'generation': GENERATION,
    }
    status.update(overrides)
    return status


def test_validate_identity_accepts_exact_release_and_pool_identity():
    assert validate_identity(RELEASE, POOL_ID) is None


@pytest.mark.parametrize('release', [
    None,
    123,
    'a' * 39 + 'g',
    'a' * 39,
    'a' * 20 + 'A' + 'a' * 19,
])
def test_validate_identity_rejects_invalid_release_with_valid_pool(release):
    with pytest.raises(ValueError):
        validate_identity(release, POOL_ID)


@pytest.mark.parametrize('pool_id', [
    None,
    123,
    '',
    'Blue_pool',
    'blue pool',
    'blue\nproxy',
    'blue; proxy_pass http://evil',
    'b' * 101,
])
def test_validate_identity_rejects_invalid_pool_with_valid_release(pool_id):
    with pytest.raises(ValueError):
        validate_identity(RELEASE, pool_id)


@pytest.mark.parametrize('ready_peers', [2, 32])
def test_candidate_accepts_matching_release_pool_and_strict_ready_status(ready_peers):
    assert candidate(valid_status(readyPeers=ready_peers), RELEASE, POOL_ID) == (GENERATION, ready_peers)


@pytest.mark.parametrize('status', [None, [], 'status', 1])
def test_candidate_rejects_non_dict_status(status):
    assert candidate(status, RELEASE, POOL_ID) is None


@pytest.mark.parametrize('missing_field', [
    'deploymentSha',
    'poolId',
    'available',
    'deploymentReady',
    'draining',
    'readyPeers',
    'generation',
])
def test_candidate_rejects_status_missing_required_field(missing_field):
    status = valid_status()
    del status[missing_field]
    assert candidate(status, RELEASE, POOL_ID) is None


@pytest.mark.parametrize('field,value', [
    ('deploymentSha', 'b' * 40),
    ('poolId', 'green_pool'),
])
def test_candidate_rejects_wrong_release_or_pool(field, value):
    assert candidate(valid_status(**{field: value}), RELEASE, POOL_ID) is None


@pytest.mark.parametrize('ready_peers', [0, 1, 33, 100])
def test_candidate_rejects_ready_peer_counts_outside_two_through_thirty_two(ready_peers):
    assert candidate(valid_status(readyPeers=ready_peers), RELEASE, POOL_ID) is None


@pytest.mark.parametrize('ready_peers', [True, False, 2.0, '2', None])
def test_candidate_requires_ready_peer_count_to_be_a_real_integer(ready_peers):
    assert candidate(valid_status(readyPeers=ready_peers), RELEASE, POOL_ID) is None


@pytest.mark.parametrize('field,value', [
    ('available', False),
    ('available', 1),
    ('deploymentReady', False),
    ('deploymentReady', 1),
    ('draining', True),
    ('draining', 0),
])
def test_candidate_rejects_non_ready_boolean_flags(field, value):
    assert candidate(valid_status(**{field: value}), RELEASE, POOL_ID) is None


@pytest.mark.parametrize('generation', [
    'b' * 31,
    'b' * 33,
    'B' * 32,
    'b' * 16 + '-' + 'b' * 15,
    None,
])
def test_candidate_rejects_invalid_generation(generation):
    assert candidate(valid_status(generation=generation), RELEASE, POOL_ID) is None
