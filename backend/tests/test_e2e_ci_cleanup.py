"""The optional Docker E2E job cleans only its recorded stack ownership."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
E2E_SCRIPT = ROOT / "scripts" / "e2e_stack_test.py"


def _e2e_job() -> dict:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["e2e-stack"]


def _named_steps(job: dict) -> dict[str, dict]:
    return {step["name"]: step for step in job["steps"] if "name" in step}


def test_e2e_cleanup_is_nonce_aware_and_always_runs():
    job = _e2e_job()
    steps = _named_steps(job)
    run = steps["Run Docker E2E"]
    cleanup = steps["Clean Up Docker Stack"]

    assert run["run"] == "python3 scripts/e2e_stack_test.py"
    assert cleanup["if"] == "always()"
    assert cleanup["id"] == "e2e-stack-cleanup"
    assert cleanup["run"] == "python3 scripts/e2e_stack_test.py --cleanup"

    source = E2E_SCRIPT.read_text(encoding="utf-8")
    assert ".e2e-stack-owner.json" in source
    assert "if sys.argv[1:] == ['--cleanup']:" in source
    assert "with workspace_lock(ROOT_DIR, recovery=True):" in source
    assert "if restore_ownership():" in source


def test_e2e_job_has_no_default_compose_teardown_or_suppressed_cleanup():
    source = WORKFLOW.read_text(encoding="utf-8")
    start = source.index("  e2e-stack:")
    end = source.index("  browser-e2e:", start)
    e2e_source = source[start:end]

    assert "docker compose logs" not in e2e_source
    assert "docker compose down" not in e2e_source
    assert "|| true" not in e2e_source


def test_e2e_run_does_not_inject_release_or_github_token_environment():
    run = _named_steps(_e2e_job())["Run Docker E2E"]
    environment = run.get("env") or {}

    assert "GITHUB_TOKEN" not in environment
    assert "BPP_USE_RELEASE_BINARY" not in environment


def test_bounded_builder_cleanup_follows_stack_cleanup():
    steps = _e2e_job()["steps"]
    cleanup_index = next(
        index for index, step in enumerate(steps)
        if step.get("name") == "Clean Up Docker Stack"
    )
    builder_index = next(
        index for index, step in enumerate(steps)
        if step.get("name") == "Remove bounded CI BuildKit builder"
    )
    builder_cleanup = steps[builder_index]

    assert cleanup_index < builder_index
    assert builder_cleanup["if"] == "${{ always() && steps.e2e-stack-cleanup.outcome == 'success' }}"
    assert builder_cleanup["run"] == "bash scripts/cleanup_ci_builder.sh"
