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


def test_image_lock_records_node_lts_for_the_glibc_npm_builder_and_alpine_sandbox():
    lock = json.loads(read("runtime/image-lock.json"))

    assert lock["images"]["node"]["nodeVersion"] == NODE_VERSION
    assert lock["images"]["nodeRuntime"]["nodeVersion"] == NODE_VERSION
    assert lock["images"]["nodeSandbox"]["nodeVersion"] == NODE_VERSION
    assert "alpine" not in lock["images"]["nodeRuntime"]["tag"]
    assert "alpine" in lock["images"]["nodeSandbox"]["tag"]


def test_runtime_uses_pinned_glibc_npm_builder_and_final_alpine_sandbox_stage():
    dockerfile = read("runtime/docker/Dockerfile")
    expected_builder = f"FROM {locked_image('nodeRuntime')} AS node-runtime"
    expected_sandbox = f"FROM {locked_image('nodeSandbox')} AS sandbox-runtime"

    assert expected_builder in dockerfile
    assert expected_sandbox in dockerfile
    assert "nodesource" not in dockerfile.lower()
    assert "setup_20" not in dockerfile.lower()
    assert "setup-node" not in dockerfile.lower()
    assert "apt-get install" in dockerfile
    assert "apk add --no-cache" in dockerfile


def test_npm_builder_and_final_sandbox_use_their_respective_node_stages():
    dockerfile = read("runtime/docker/Dockerfile")

    assert "COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node" in dockerfile
    assert "COPY --from=node-runtime /usr/local/lib/node_modules" not in dockerfile
    assert "ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm" in dockerfile
    assert "ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx" in dockerfile
    assert "ln -s node /usr/local/bin/nodejs" in dockerfile
    assert f'test "$(node --version)" = v{NODE_VERSION};' in dockerfile
    assert f'test "$(npm --version)" = {NPM_VERSION};' in dockerfile
    assert "rm -rf /usr/local/lib/node_modules/npm" in dockerfile
    assert "COPY --from=bpp-build /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm" in dockerfile
    assert "printf '40 2\\n' | node -e" in dockerfile


def test_glibc_npm_builder_verifies_the_fixed_tree_before_bpp_checkout_or_alpine_copy():
    dockerfile = read("runtime/docker/Dockerfile")

    download_at = dockerfile.index(NPM_TARBALL_URL)
    verify_at = dockerfile.index(
        f"{NPM_TARBALL_SHA256} /tmp/npm.tgz | sha256sum --check --strict"
    )
    extract_at = dockerfile.index("tar -xzf /tmp/npm.tgz --strip-components=1 -C /usr/local/lib/node_modules/npm")
    version_at = dockerfile.index(f'test "$(npm --version)" = {NPM_VERSION};')
    compiler_at = dockerfile.index("\nARG BPP_REPO=", version_at)
    alpine_copy_at = dockerfile.index("COPY --from=bpp-build /usr/local/lib/node_modules/npm ")

    assert download_at < verify_at < extract_at < version_at < compiler_at < alpine_copy_at
    assert "mkdir -p /usr/local/lib/node_modules/npm" in dockerfile
    assert "rm /tmp/npm.tgz" in dockerfile


def test_glibc_builder_checks_node_libraries_and_final_alpine_submission_user_checks_tools():
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
