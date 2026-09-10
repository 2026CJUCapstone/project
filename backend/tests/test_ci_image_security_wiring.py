"""CI wiring keeps installed-image security scans unconditional and bounded."""

from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
TRIVY_SHA256 = "2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a"


def image_security_job():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["image-security"]


def steps_by_name(job):
    return {step["name"]: step for step in job["steps"]}


def test_image_security_job_is_unconditional_and_waits_for_all_build_gates():
    job = image_security_job()

    assert not job.get("if")
    assert not job.get("continue-on-error")
    assert set(job["needs"]) == {"backend-tests", "frontend-checks", "compose-config"}


def test_trivy_download_is_fixed_linux_archive_and_verified_before_extraction():
    job = image_security_job()
    steps = steps_by_name(job)
    download = steps["Download hash-pinned Trivy"]
    run = download["run"]

    assert "trivy-0.74.0" in run
    assert (
        "https://github.com/aquasecurity/trivy/releases/download/"
        "v0.74.0/trivy_0.74.0_Linux-64bit.tar.gz"
    ) in run
    checksum = re.escape(
        f"printf '%s  %s\\n' {TRIVY_SHA256} \"$scanner/release.tar.gz\""
    )
    assert re.search(checksum + r" \| sha256sum --check --strict", run)
    assert run.index("sha256sum --check --strict") < run.index("tar -xzf")

    scan = steps["Build and scan immutable application images"]
    assert job["steps"].index(download) < job["steps"].index(scan)
    assert '"$RUNNER_TEMP/trivy-0.74.0/trivy"' in scan["run"]


def test_scan_uses_exact_github_commit_and_bounded_builder_cleanup():
    job = image_security_job()
    steps = steps_by_name(job)
    setup = steps["Setup bounded BuildKit builder"]
    scan = steps["Build and scan immutable application images"]
    cleanup = steps["Remove bounded CI BuildKit builder"]

    assert setup["uses"] == "./.github/actions/setup-bounded-builder"
    assert job["steps"].index(setup) < job["steps"].index(scan)
    assert scan["run"].count('python3 scripts/ci_image_security.py') == 1
    assert '--commit "$GITHUB_SHA"' in scan["run"]
    assert '--output-dir "$RUNNER_TEMP/application-image-security"' in scan["run"]
    assert '--cache-dir "$RUNNER_TEMP/trivy-cache"' in scan["run"]

    assert cleanup["if"] == "always()"
    assert cleanup["run"] == "bash scripts/cleanup_ci_builder.sh"
    assert job["steps"].index(cleanup) > job["steps"].index(scan)


def test_image_security_job_has_no_deploy_or_push_commands():
    job = image_security_job()
    commands = "\n".join(step.get("run", "") for step in job["steps"])

    assert not re.search(r"\bdocker\s+(?:\S+\s+)*push\b", commands)
    assert not re.search(r"\bdocker\s+(?:\S+\s+)*login\b", commands)
    assert not re.search(r"\bdocker\s+compose\s+up\b", commands)
    assert not re.search(r"\bdeploy\b", commands, re.IGNORECASE)
