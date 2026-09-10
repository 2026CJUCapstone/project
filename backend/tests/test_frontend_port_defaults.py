"""Frontend container mappings use the image's internal port 8080."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("relative_path", "mapping"),
    [
        (
            "scripts/docker_up.sh",
            'export WEBCOMPILER_FRONTEND_PORT_MAPPING="${WEBCOMPILER_FRONTEND_PORT_MAPPING:-127.0.0.1:15180:8080}"',
        ),
        (
            "scripts/docker_up_webcompiler.sh",
            'export WEBCOMPILER_FRONTEND_PORT_MAPPING="${WEBCOMPILER_FRONTEND_PORT_MAPPING:-127.0.0.1:15173:8080}"',
        ),
        (
            "scripts/e2e_stack_test.py",
            '"WEBCOMPILER_FRONTEND_PORT_MAPPING": f"127.0.0.1:{FRONTEND_PORT}:8080",',
        ),
        (
            "scripts/quantitative_eval.py",
            '"WEBCOMPILER_FRONTEND_PORT_MAPPING": f"127.0.0.1:{FRONTEND_PORT}:8080",',
        ),
    ],
)
def test_frontend_mapping_defaults_to_internal_port_8080(relative_path, mapping):
    source = (ROOT / relative_path).read_text(encoding="utf-8")

    assert mapping in source
