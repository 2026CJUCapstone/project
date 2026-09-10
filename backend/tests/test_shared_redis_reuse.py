import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ensure_shared_redis.py"


def load_script():
    spec = importlib.util.spec_from_file_location(
        "ensure_shared_redis_reuse_under_test", SCRIPT
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses inspects sys.modules while processing the class annotations.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ensure_shared_redis = load_script()


def make_config(tmp_path):
    return ensure_shared_redis.Config(root=str(tmp_path / "deployment"))


def valid_volume(config):
    return {
        "Name": config.volume,
        "Driver": "local",
        "Options": {},
        "Labels": dict(config.labels),
    }


def valid_container(config, *, running=True):
    return {
        "Id": "shared-redis-container-id",
        "Config": {
            "Labels": dict(config.labels),
            "Image": config.image,
            "Cmd": list(config.command),
        },
        "HostConfig": {
            "PortBindings": {},
            "PublishAllPorts": False,
            "Privileged": False,
            "ReadonlyRootfs": True,
            "Memory": config.memory_mb * 1024 * 1024,
            "MemorySwap": config.memory_mb * 1024 * 1024,
            "NanoCpus": config.cpu_millis * 1_000_000,
            "PidsLimit": 128,
            "RestartPolicy": {"Name": "unless-stopped", "MaximumRetryCount": 0},
            "SecurityOpt": ["no-new-privileges:true"],
            "LogConfig": {
                "Type": "json-file",
                "Config": {"max-size": "10m", "max-file": "3"},
            },
        },
        "NetworkSettings": {
            "Networks": {config.network: {"NetworkID": "shared-network-id"}},
        },
        "Mounts": [
            {
                "Type": "volume",
                "Name": config.volume,
                "Source": "/var/lib/docker/volumes/" + config.volume + "/_data",
                "Destination": "/data",
                "Driver": "local",
                "Mode": "",
                "RW": True,
                "Propagation": "",
            },
            {
                "Type": "tmpfs",
                "Name": "",
                "Source": "tmpfs",
                "Destination": "/tmp",
                "Mode": "rw,noexec,nosuid,size=16m",
                "RW": True,
                "Propagation": "",
            },
        ],
        "State": {"Running": running},
    }


class FakeDocker:
    """Small in-memory Docker CLI surface for ensure() regression tests."""

    def __init__(self, config, *, container=None, volume=None):
        self.config = config
        self.network = {"Driver": "bridge", "Scope": "local"}
        self.volume = volume or valid_volume(config)
        self.container = container or valid_container(config)
        self.calls = []

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)

        if args[:2] == ["network", "inspect"]:
            return json.dumps([self.network])
        if args[:2] == ["image", "inspect"]:
            return "{}"
        if args[:2] == ["volume", "ls"]:
            return self.config.volume + "\n"
        if args[:2] == ["volume", "create"]:
            return self.config.volume + "\n"
        if args[:2] == ["volume", "inspect"]:
            return json.dumps([self.volume])
        if args[:2] == ["container", "ls"]:
            return self.config.name + "\n"
        if args[:2] == ["container", "inspect"]:
            return json.dumps([self.container])
        if args and args[0] == "run":
            raise AssertionError("the reuse fixture should never recreate its container")
        if args and args[0] == "start":
            assert args[1] == self.config.name
            self.container["State"]["Running"] = True
            return ""
        if args and args[0] == "exec":
            assert args[1:4] == [self.config.name, "redis-cli", "ping"]
            return "PONG\n"
        raise AssertionError(f"unexpected fake Docker command: {args!r}")


def ensure_with_fake(config, fake):
    return ensure_shared_redis.ensure(config, call=fake)


def assert_no_mutating_container_call(fake):
    assert not any(args and args[0] in {"run", "start", "rm", "rename"} for args in fake.calls)


def test_foreign_volume_is_refused_before_container_inspection(tmp_path):
    config = make_config(tmp_path)
    volume = valid_volume(config)
    volume["Labels"] = {
        "io.webcompiler.shared.role": "redis",
        "io.webcompiler.owner": "different-deployment",
    }
    fake = FakeDocker(config, volume=volume)

    with pytest.raises(ensure_shared_redis.SharedRedisError, match="Refusing"):
        ensure_with_fake(config, fake)

    assert not any(args[:2] == ["container", "inspect"] for args in fake.calls)
    assert_no_mutating_container_call(fake)


def test_foreign_container_is_refused_without_recreate_or_start(tmp_path):
    config = make_config(tmp_path)
    container = valid_container(config)
    container["Config"]["Labels"] = {
        "io.webcompiler.shared.role": "redis",
        "io.webcompiler.owner": "different-deployment",
    }
    fake = FakeDocker(config, container=container)

    with pytest.raises(ensure_shared_redis.SharedRedisError, match="(?:Refusing|differs)"):
        ensure_with_fake(config, fake)

    assert_no_mutating_container_call(fake)


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(
            lambda container: container["HostConfig"].update(
                Memory=container["HostConfig"]["Memory"] + 1
            ),
            id="changed-memory",
        ),
        pytest.param(
            lambda container: container["HostConfig"].update(
                PortBindings={"6379/tcp": [{"HostPort": "6379"}]}
            ),
            id="exposed-port",
        ),
        pytest.param(
            lambda container: container["HostConfig"].update(PublishAllPorts=True),
            id="automatic-published-ports",
        ),
        pytest.param(
            lambda container: container["HostConfig"].update(SecurityOpt=[]),
            id="missing-no-new-privileges",
        ),
        pytest.param(
            lambda container: container["HostConfig"].update(LogConfig={"Type":"json-file", "Config":{}}),
            id="unbounded-logs",
        ),
        pytest.param(
            lambda container: container["Mounts"].append(
                {
                    "Type": "volume",
                    "Name": "attacker-data",
                    "Destination": "/etc",
                    "RW": True,
                }
            ),
            id="extra-mount",
        ),
        pytest.param(
            lambda container: container["NetworkSettings"]["Networks"].update(
                {"attacker-network": {}}
            ),
            id="extra-network",
        ),
    ],
)
def test_changed_or_exposed_container_configuration_is_refused(tmp_path, mutate):
    config = make_config(tmp_path)
    container = valid_container(config)
    mutate(container)
    fake = FakeDocker(config, container=container)

    with pytest.raises(ensure_shared_redis.SharedRedisError, match="differs"):
        ensure_with_fake(config, fake)

    assert_no_mutating_container_call(fake)


def test_matching_configuration_reuses_the_same_container_id(tmp_path):
    config = make_config(tmp_path)
    container = valid_container(config)
    original_id = container["Id"]
    fake = FakeDocker(config, container=container)

    assert ensure_with_fake(config, fake) is None

    assert fake.container["Id"] == original_id
    assert_no_mutating_container_call(fake)
    assert any(args[:2] == ["container", "inspect"] for args in fake.calls)
    assert any(args and args[0] == "exec" for args in fake.calls)


def test_stopped_matching_container_is_started_without_recreation(tmp_path):
    config = make_config(tmp_path)
    container = valid_container(config, running=False)
    original_id = container["Id"]
    fake = FakeDocker(config, container=container)

    assert ensure_with_fake(config, fake) is None

    assert fake.container["Id"] == original_id
    assert fake.container["State"]["Running"] is True
    assert [args for args in fake.calls if args and args[0] == "start"] == [
        ["start", config.name]
    ]
    assert not any(args and args[0] == "run" for args in fake.calls)
