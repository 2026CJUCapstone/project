"""Static frontend image contract; actual constrained builds are tested elsewhere."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "frontend" / "Dockerfile"


def stages():
    lines = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    from_lines = [index for index, line in enumerate(lines) if line.startswith("FROM ")]
    assert len(from_lines) == 2
    return "\n".join(lines[: from_lines[1]]), "\n".join(lines[from_lines[1] :])


def test_frontend_build_uses_one_build_only_heap_cap_command():
    build_stage, _ = stages()
    command = "RUN NODE_OPTIONS=--max-old-space-size=1536 npm run build"

    assert build_stage.count(command) == 1
    assert build_stage.count("npm run build") == 1


def test_final_runtime_stage_has_no_node_build_tooling_or_heap_setting():
    _, runtime_stage = stages()

    assert "NODE_OPTIONS" not in runtime_stage
    assert "npm ci" not in runtime_stage
    assert "npm run build" not in runtime_stage
    assert "node_modules" not in runtime_stage
    assert "COPY --from=build /app/dist /usr/share/nginx/html" in runtime_stage
