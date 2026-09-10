import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release_e2e_build_cache.py"


def load_script():
    spec = importlib.util.spec_from_file_location("e2e_build_cache_release", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def scope(module, root):
    project = "webcompiler-e2e-" + "a" * 32
    return module.Scope(
        root=root.resolve(),
        project=project,
        builder="audit-builder",
        builder_id="b" * 64,
        sandbox_image=project + "-sandbox:latest",
        backend_image=project + "-backend:latest",
        frontend_image=project + "-frontend:latest",
    )


def test_release_is_scoped_to_private_nonce_images_and_bound_builder(tmp_path):
    module = load_script()
    selected = scope(module, tmp_path)
    module.validate_owner_record(
        {"version": 1, "root": str(selected.root), "namespace": selected.project},
        selected.root,
        selected.project,
    )
    image_ids = {image: "sha256:" + char * 64 for image, char in zip(selected.images, "cde")}
    calls, verifies, inspected = [], [], []

    module.release(
        selected,
        verify_builder=lambda: verifies.append(True) or selected.builder_id,
        inspect_image=lambda image: inspected.append(image) or image_ids[image],
        prune_builder=lambda builder: calls.append(builder),
        read_owner=lambda root, project: module.validate_owner_record(
            {"version": 1, "root": str(root), "namespace": project}, root, project
        ),
    )

    assert calls == ["audit-builder"]
    assert verifies == [True, True]
    assert inspected == [*selected.images, *selected.images]
    assert module.prune_command(selected.builder) == [
        "docker", "buildx", "prune", "--builder", "audit-builder", "--all", "--force"
    ]


def test_release_refuses_journal_mismatch_before_docker_actions(tmp_path):
    module = load_script()
    selected = scope(module, tmp_path)
    calls = []

    with pytest.raises(module.CacheReleaseError, match="ownership journal"):
        module.release(
            selected,
            verify_builder=lambda: calls.append("verify") or selected.builder_id,
            inspect_image=lambda image: calls.append(("inspect", image)) or "sha256:" + "c" * 64,
            prune_builder=lambda builder: calls.append(("prune", builder)),
            read_owner=lambda root, project: module.validate_owner_record(
                {"version": 1, "root": str(root), "namespace": "webcompiler-e2e-" + "f" * 32},
                root,
                project,
            ),
        )
    assert calls == []


def test_scope_rejects_non_e2e_project_and_any_foreign_image_tag(tmp_path):
    module = load_script()
    with pytest.raises(module.CacheReleaseError, match="E2E project namespace"):
        module.Scope(
            tmp_path.resolve(), "webcompiler", "audit-builder", "b" * 64,
            "webcompiler-sandbox:latest", "webcompiler-backend:latest", "webcompiler-frontend:latest",
        )
    project = "webcompiler-e2e-" + "a" * 32
    with pytest.raises(module.CacheReleaseError, match="image tags"):
        module.Scope(
            tmp_path.resolve(), project, "audit-builder", "b" * 64,
            project + "-sandbox:latest", "production-backend:latest", project + "-frontend:latest",
        )


def test_parse_scope_refuses_prune_builder_different_from_verifier_environment(tmp_path, monkeypatch):
    module = load_script()
    selected = scope(module, tmp_path)
    monkeypatch.setenv("WEBCOMPILER_BUILD_BUILDER", "bound-builder")
    monkeypatch.setenv("WEBCOMPILER_BUILD_CONTAINER_ID", selected.builder_id)
    arguments = module.argparse.Namespace(
        root=selected.root,
        project=selected.project,
        builder="different-builder",
        sandbox_image=selected.sandbox_image,
        backend_image=selected.backend_image,
        frontend_image=selected.frontend_image,
        validate_only=False,
    )
    with pytest.raises(module.CacheReleaseError, match="differs from the verified builder"):
        module.parse_scope(arguments)


@pytest.mark.skipif(os.name != "posix", reason="private ownership descriptor checks are POSIX-only")
def test_private_root_bound_journal_is_required(tmp_path):
    module = load_script()
    selected = scope(module, tmp_path)
    journal = selected.root / ".e2e-stack-owner.json"
    journal.write_text(json.dumps({
        "version": 1, "root": str(selected.root), "namespace": selected.project,
    }), encoding="utf-8")
    journal.chmod(0o600)
    module.read_owner_record(selected.root, selected.project)
    journal.chmod(0o640)
    with pytest.raises(module.CacheReleaseError, match="private E2E ownership journal"):
        module.read_owner_record(selected.root, selected.project)


def test_release_fails_closed_when_a_tag_changes_after_prune(tmp_path):
    module = load_script()
    selected = scope(module, tmp_path)
    ids = {image: "sha256:" + char * 64 for image, char in zip(selected.images, "cde")}
    observed, pruned = {}, []

    def inspect(image):
        count = observed.get(image, 0)
        observed[image] = count + 1
        if image == selected.frontend_image and count:
            return "sha256:" + "f" * 64
        return ids[image]

    with pytest.raises(module.CacheReleaseError, match="identity changed"):
        module.release(
            selected,
            verify_builder=lambda: selected.builder_id,
            inspect_image=inspect,
            prune_builder=lambda builder: pruned.append(builder),
            read_owner=lambda *_: None,
        )
    assert pruned == [selected.builder]


def test_release_never_prunes_when_bound_builder_verification_changes(tmp_path):
    module = load_script()
    selected = scope(module, tmp_path)
    calls = []
    with pytest.raises(module.CacheReleaseError, match="builder identity changed before"):
        module.release(
            selected,
            verify_builder=lambda: "c" * 64,
            inspect_image=lambda image: calls.append(("inspect", image)) or "sha256:" + "d" * 64,
            prune_builder=lambda builder: calls.append(("prune", builder)),
            read_owner=lambda *_: None,
        )
    assert calls == []


def test_docker_up_only_releases_cache_after_both_builds_and_before_up():
    source = (ROOT / "scripts" / "docker_up.sh").read_text(encoding="utf-8")
    assert "WEBCOMPILER_E2E_RELEASE_BUILD_CACHE" in source
    assert "release_e2e_build_cache.py" in source
    assert source.index("--validate-only") < source.index('mkdir -p "$PROJECT_ROOT/.sandbox-work"')
    sandbox_build = source.index('bash "$PROJECT_ROOT/scripts/build_sandbox_image.sh"')
    compose_build = source.index('docker compose build --builder "$WEBCOMPILER_BUILD_BUILDER"')
    release = source.index("release_e2e_build_cache\n", compose_build)
    compose_up = source.index("docker compose up --no-build -d")
    assert sandbox_build < compose_build < release < compose_up
