"""Static Node LTS wiring checks; runtime execution is validated separately."""

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
NODE_VERSION = "24.21.0"
NPM_VERSION = "11.19.1"
NPM_TARBALL_URL = "https://registry.npmjs.org/npm/-/npm-11.19.1.tgz"
NPM_TARBALL_SHA256 = "9f58bff01604cb1b14008fef14dceb14d836a49225e45c6c2e37de3be3e707f0"


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def locked_image(name):
    lock = json.loads(read("runtime/image-lock.json"))
    image = lock["images"][name]
    repository = image["repository"].removeprefix("library/")
    return f"{repository}:{image['tag']}@{image['digest']}"


def test_ci_and_frontend_pin_node_lts_exactly():
    workflow = read(".github/workflows/ci.yml")
    setup_versions = re.findall(
        r'^\s*node-version:\s*["\']([^"\']+)["\']\s*$',
        workflow,
        flags=re.MULTILINE,
    )

    assert workflow.count("uses: actions/setup-node@v4") == 2
    assert setup_versions == [NODE_VERSION, NODE_VERSION]
    assert (ROOT / "frontend" / ".nvmrc").read_text(encoding="utf-8") == NODE_VERSION + "\n"


def test_image_lock_records_the_same_node_lts_for_build_and_runtime():
    lock = json.loads(read("runtime/image-lock.json"))

    assert lock["images"]["node"]["nodeVersion"] == NODE_VERSION
    assert lock["images"]["nodeRuntime"]["nodeVersion"] == NODE_VERSION
    assert "alpine" not in lock["images"]["nodeRuntime"]["tag"]


def test_runtime_image_uses_pinned_glibc_node_stage_and_no_nodesource_setup():
    dockerfile = read("runtime/docker/Dockerfile")
    expected_from = f"FROM {locked_image('nodeRuntime')} AS node-runtime"

    assert expected_from in dockerfile
    assert "FROM node:24-alpine" not in dockerfile
    assert "nodesource" not in dockerfile.lower()
    assert "setup_20" not in dockerfile.lower()
    assert "setup-node" not in dockerfile.lower()
    assert "apt-get install" in dockerfile


def test_runtime_copies_only_pinned_node_binary_and_exposes_checked_tools():
    dockerfile = read("runtime/docker/Dockerfile")

    assert "COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node" in dockerfile
    assert "COPY --from=node-runtime /usr/local/lib/node_modules" not in dockerfile
    assert "ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm" in dockerfile
    assert "ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx" in dockerfile
    assert "ln -s node /usr/local/bin/nodejs" in dockerfile
    assert f'test "$(node --version)" = v{NODE_VERSION};' in dockerfile
    assert f'test "$(npm --version)" = {NPM_VERSION};' in dockerfile
    assert "printf '40 2\\n' | node -e" in dockerfile


def test_runtime_downloads_and_verifies_the_fixed_npm_tree_before_extracting_it():
    dockerfile = read("runtime/docker/Dockerfile")

    download_at = dockerfile.index(NPM_TARBALL_URL)
    verify_at = dockerfile.index(
        f"{NPM_TARBALL_SHA256} /tmp/npm.tgz | sha256sum --check --strict"
    )
    extract_at = dockerfile.index("tar -xzf /tmp/npm.tgz --strip-components=1 -C /usr/local/lib/node_modules/npm")
    version_at = dockerfile.index(f'test "$(npm --version)" = {NPM_VERSION};')

    assert download_at < verify_at < extract_at < version_at
    assert "mkdir -p /usr/local/lib/node_modules/npm" in dockerfile
    assert "rm /tmp/npm.tgz" in dockerfile


def test_runtime_checks_dynamic_libraries_and_actual_submission_user_tools():
    dockerfile = read("runtime/docker/Dockerfile")
    assert 'ldd /usr/local/bin/node > /tmp/node-libraries.txt' in dockerfile
    assert "! grep -q 'not found' /tmp/node-libraries.txt" in dockerfile
    nonroot = dockerfile.split('USER sandboxuser\n', 1)[1]
    assert 'test "$(nodejs --version)" = v24.21.0' in nonroot
    assert 'npm --version' in nonroot and 'npx --version' in nonroot
    assert "printf '40 2\\n' | node -e" in nonroot


def test_dompurify_optional_types_exist_in_the_clean_install_lock():
    packages = json.loads(read('frontend/package-lock.json'))['packages']
    assert '@types/trusted-types' in packages['node_modules/dompurify']['optionalDependencies']
    types = packages['node_modules/@types/trusted-types']
    assert types['version'] == '2.0.7'
    assert types['optional'] is True
    assert types['integrity'].startswith('sha512-')
