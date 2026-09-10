"""Pinned image defaults stay aligned with the checked-in image lock."""

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
LOCK = json.loads((ROOT / "runtime" / "image-lock.json").read_text(encoding="utf-8"))


def locked_image(name):
    image = LOCK["images"][name]
    repository = image["repository"]
    if repository.startswith("library/"):
        repository = repository.removeprefix("library/")
    return f"{repository}:{image['tag']}@{image['digest']}"


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


def from_lines(path):
    return [line for line in source(path).splitlines() if line.startswith("FROM ")]


def test_application_dockerfiles_use_exact_locked_base_image_lines():
    assert from_lines("backend/Dockerfile") == [f"FROM {locked_image('python')}"]
    assert from_lines("frontend/Dockerfile") == [
        f"FROM {locked_image('node')} AS build",
        f"FROM {locked_image('nginx')}",
    ]
    assert from_lines("runtime/docker/Dockerfile") == [
        f"FROM {locked_image('nodeRuntime')} AS node-runtime",
        f"FROM {locked_image('ubuntu')}",
    ]


def test_compose_service_defaults_use_locked_stateful_and_load_balancer_images():
    compose = source("docker-compose.yml")
    load_balancer = source("docker-compose.lb.yml")

    assert f"image: {locked_image('postgres')}" in compose
    assert f"image: {locked_image('redis')}" in compose
    assert f"image: {locked_image('pgbouncer')}" in compose
    assert f"image: ${{WEBCOMPILER_NGINX_IMAGE:-{locked_image('nginx')}}}" in load_balancer


def test_scripts_and_audit_compose_repeat_the_same_locked_defaults():
    postgres = locked_image("postgres")
    redis = locked_image("redis")
    nginx = locked_image("nginx")

    postgres_script = source("scripts/ensure_shared_postgres.py")
    redis_script = source("scripts/ensure_shared_redis.py")
    edge_runtime = source("scripts/edge_runtime.py")
    deploy = source("scripts/deploy_server.sh")
    audit = source("scripts/audit-staging.compose.yml")

    assert f"image: str = '{postgres}'" in postgres_script
    assert f"image=os.getenv('WEBCOMPILER_SHARED_POSTGRES_IMAGE', '{postgres}')" in postgres_script
    assert f"image: str = '{redis}'" in redis_script
    assert f"image=os.getenv('WEBCOMPILER_SHARED_REDIS_IMAGE','{redis}')" in redis_script
    assert f"image='" + nginx + "'" in edge_runtime
    assert f"SHARED_POSTGRES_IMAGE=\"${{WEBCOMPILER_SHARED_POSTGRES_IMAGE:-{postgres}}}\"" in deploy
    assert f"image: {postgres}" in audit
    assert f"image: {redis}" in audit


def test_operator_image_overrides_remain_available():
    postgres_script = source("scripts/ensure_shared_postgres.py")
    redis_script = source("scripts/ensure_shared_redis.py")
    load_balancer = source("docker-compose.lb.yml")
    compose = source("docker-compose.yml")
    deploy = source("scripts/deploy_server.sh")

    assert "os.getenv('WEBCOMPILER_SHARED_POSTGRES_IMAGE'" in postgres_script
    assert "os.getenv('WEBCOMPILER_SHARED_REDIS_IMAGE'" in redis_script
    assert "${WEBCOMPILER_NGINX_IMAGE:-" in load_balancer
    assert "${WEBCOMPILER_BACKEND_IMAGE:-" in compose
    assert "${WEBCOMPILER_SHARED_POSTGRES_IMAGE:-" in deploy
