"""A new default pin must not silently upgrade/adopt existing stateful data."""
from dataclasses import replace

import pytest

from tests.test_shared_redis_reuse import (make_config, valid_container, FakeDocker,
    ensure_shared_redis, ensure_with_fake, assert_no_mutating_container_call)
from tests.test_shared_postgres import shared, Docker, IMAGE


def test_new_redis_default_refuses_old_tag_created_container(tmp_path):
    config = make_config(tmp_path)
    assert '@sha256:' in config.image
    container = valid_container(config, running=False)
    container['Config']['Image'] = 'redis:7-alpine'
    fake = FakeDocker(config, container=container)
    with pytest.raises(ensure_shared_redis.SharedRedisError, match='differs from the approved configuration'):
        ensure_with_fake(config, fake)
    assert ['image', 'inspect', config.image] in fake.calls
    assert_no_mutating_container_call(fake)


def test_explicit_redis_override_is_preserved_without_recreating_matching_container(tmp_path):
    config = replace(make_config(tmp_path), image='example/approved-redis@sha256:' + '8' * 64)
    fake = FakeDocker(config)
    ensure_with_fake(config, fake)
    assert ['image', 'inspect', config.image] in fake.calls
    assert_no_mutating_container_call(fake)


def test_postgres_default_is_resolved_then_existing_different_content_refused(tmp_path):
    config = shared.Config(root=str(tmp_path / 'deployment'), password='fixture-only-credential-12345')
    assert '@sha256:' in config.image
    fake = Docker(config, existing=True)
    fake.state['container']['Image'] = 'sha256:' + '8' * 64
    with pytest.raises(shared.SharedPostgresError):
        shared.ensure(config, call=fake)
    assert (['image', 'inspect', config.image], None) in fake.calls
    assert fake.mutations == []


def test_explicit_postgres_override_still_creates_by_resolved_id(tmp_path):
    config = shared.Config(root=str(tmp_path / 'deployment'), password='fixture-only-credential-12345',
        image='example/approved-postgres@sha256:' + '8' * 64)
    fake = Docker(config)
    shared.ensure(config, call=fake)
    assert (['image', 'inspect', config.image], None) in fake.calls
    create = next(args for args, _ in fake.calls if args[0] == 'create')
    assert create[-len(config.command)-1:] == [IMAGE, *config.command]
    assert config.image not in create
