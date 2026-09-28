import json

import pytest

from app.services.compiler import DockerCompilerRunner
from app.services.compiler_graphs import build_bpp_pipeline_from_json


SOURCE = "// 한글 😀\r\nfunc main() -> u64 { return 0; }\r\n"


def _return_range(source: str = SOURCE) -> dict:
    start = source.encode("utf-8").index(b"return 0;")
    return {
        "rangeId": "return-zero",
        "astNodeId": "ast-return-zero",
        "file": "/tmp/bpp/src/user/main.bpp",
        "startLine": 2,
        "startColumn": 22,
        "endLine": 2,
        "endColumn": 31,
        "startOffset": start,
        "endOffset": start + len(b"return 0;"),
    }


def _nested_ir_view(source: str = SOURCE, *, functions: list[dict] | None = None) -> dict:
    if functions is None:
        functions = [
            {
                "name": "main",
                "blocks": [
                    {
                        "id": "b0",
                        "instructions": [
                            {
                                "id": "ir-ret-0",
                                "opcode": "ret",
                                "operands": [{"kind": "const", "value": 0}],
                                "sourceRanges": [_return_range(source)],
                            }
                        ],
                    }
                ],
            }
        ]
    return {"ssa": {"stage": "ir", "functions": functions}}


def _unified_payload(source: str = SOURCE, *, ir_functions: list[dict] | None = None) -> dict:
    source_range = _return_range(source)
    return {
        "schemaVersion": 1,
        "sourceRangeSemantics": {
            "columnEncoding": "byte",
            "offsetEncoding": "byte",
            "endColumn": "exclusive",
        },
        "views": {
            "ast": {
                "nodes": [
                    {"id": "ast-program", "kind": "Program", "sourceRanges": []},
                    {
                        "id": "ast-return-zero",
                        "kind": "ReturnStatement",
                        "label": "return 0",
                        "sourceRanges": [source_range],
                    },
                ],
                "edges": [{"from": "ast-program", "to": "ast-return-zero"}],
            },
            "ssa": {
                "ssa": {
                    "functions": [
                        {
                            "name": "main",
                            "blocks": [
                                {
                                    "id": "b0",
                                    "instructions": [
                                        {
                                            "id": "ssa-ret-0",
                                            "opcode": "ret",
                                            "operands": [{"kind": "const", "value": 0}],
                                            "sourceRanges": [source_range],
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            },
            # The pinned compiler's unified IR view is an IR-stage SSA dump,
            # not an {"ir": {"instructions": ...}} wrapper.
            "ir": _nested_ir_view(source, functions=ir_functions),
            "asm": {
                "asm": {
                    "lines": [
                        {"text": "main:", "instruction": "", "operands": [], "sourceRanges": []},
                        {
                            "text": "    mov rax, 0",
                            "instruction": "mov",
                            "operands": ["rax", "0"],
                            "sourceRanges": [source_range],
                        },
                    ]
                }
            },
        },
    }


def test_nested_unified_ir_preserves_unicode_crlf_byte_source_ranges():
    result = build_bpp_pipeline_from_json(
        json.dumps(_unified_payload()), SOURCE, "main.bpp", {"ir"}
    )

    assert result is not None
    instructions = result["ir"]["instructions"]
    mapped = instructions[-1]["sourceRanges"][0]
    assert instructions[-1]["opcode"] == "ret"
    assert mapped["rangeId"] == "return-zero"
    assert mapped["astNodeId"] == "ast-return-zero"
    assert SOURCE.encode("utf-8")[mapped["startOffset"]:mapped["endOffset"]] == b"return 0;"
    assert mapped["startColumn"] == 22
    assert result["sourceRangeSemantics"]["offsetEncoding"] == "byte"


def test_nested_unified_ir_rejects_ssa_stage_payload():
    payload = {
        "views": {
            "ir": {
                "ssa": {
                    "stage": "ssa",
                    "functions": [{"name": "main", "blocks": []}],
                }
            }
        }
    }

    assert build_bpp_pipeline_from_json(json.dumps(payload), SOURCE, "main.bpp", {"ir"}) is None


@pytest.mark.asyncio
async def test_full_modern_unified_payload_needs_only_compile_json(monkeypatch: pytest.MonkeyPatch):
    runner = DockerCompilerRunner()
    calls: list[str] = []
    payload = _unified_payload()

    async def execute(**kwargs):
        calls.append(kwargs["mode"])
        assert kwargs["source_code"] == SOURCE
        assert kwargs["language"] == "bpp"
        if kwargs["mode"] == "compile-json":
            return {"exit_code": 0, "stdout": json.dumps(payload), "stderr": "", "execution_time": 1}
        raise AssertionError(f"unexpected fallback: {kwargs['mode']}")

    monkeypatch.setattr(runner, "_execute", execute)

    result = await runner.compile(SOURCE, "bpp", target="all")

    assert calls == ["compile-json"]
    assert result["success"] is True
    assert set(result).issuperset({"ast", "ssa", "ir", "asm"})
    mapped = result["ir"]["instructions"][-1]["sourceRanges"][0]
    assert SOURCE.encode("utf-8")[mapped["startOffset"]:mapped["endOffset"]] == b"return 0;"


@pytest.mark.asyncio
async def test_explicit_empty_unified_ir_is_resolved_without_fallback(monkeypatch: pytest.MonkeyPatch):
    runner = DockerCompilerRunner()
    calls: list[str] = []
    payload = _unified_payload(ir_functions=[])

    async def execute(**kwargs):
        calls.append(kwargs["mode"])
        if kwargs["mode"] == "compile-json":
            return {"exit_code": 0, "stdout": json.dumps(payload), "stderr": "", "execution_time": 1}
        raise AssertionError(f"unexpected fallback: {kwargs['mode']}")

    monkeypatch.setattr(runner, "_execute", execute)

    result = await runner.compile(SOURCE, "bpp", target="ir")

    assert calls == ["compile-json"]
    assert result["success"] is True
    assert result["ir"] == {"instructions": []}


@pytest.mark.asyncio
async def test_legacy_missing_unified_ir_uses_dedicated_ir_json(monkeypatch: pytest.MonkeyPatch):
    runner = DockerCompilerRunner()
    calls: list[str] = []
    dedicated_ir = {"ssa": {"stage": "ir", "functions": _nested_ir_view()["ssa"]["functions"]}}

    async def execute(**kwargs):
        calls.append(kwargs["mode"])
        if kwargs["mode"] == "compile-json":
            return {"exit_code": 0, "stdout": json.dumps({"views": {}}), "stderr": "", "execution_time": 1}
        if kwargs["mode"] == "dump-ir-json":
            return {"exit_code": 0, "stdout": json.dumps(dedicated_ir), "stderr": "", "execution_time": 1}
        raise AssertionError(f"unexpected fallback: {kwargs['mode']}")

    monkeypatch.setattr(runner, "_execute", execute)

    result = await runner.compile(SOURCE, "bpp", target="ir")

    assert calls == ["compile-json", "dump-ir-json"]
    mapped = result["ir"]["instructions"][-1]["sourceRanges"][0]
    assert SOURCE.encode("utf-8")[mapped["startOffset"]:mapped["endOffset"]] == b"return 0;"


@pytest.mark.parametrize("stage,view,field", [
    ("ast", {"nodes": [], "edges": []}, "nodes"),
    ("ssa", {"ssa": {"functions": []}}, "blocks"),
    ("ir", {"ssa": {"stage": "ir", "functions": []}}, "instructions"),
    ("asm", {"asm": {"lines": []}}, "lines"),
])
@pytest.mark.asyncio
async def test_valid_empty_views_do_not_launch_more_containers(monkeypatch, stage, view, field):
    runner = DockerCompilerRunner()
    calls = []

    async def execute(**kwargs):
        calls.append(kwargs["mode"])
        assert kwargs["mode"] == "compile-json"
        return {"exit_code": 0, "stdout": json.dumps({"views": {stage: view}}),
                "stderr": "", "execution_time": 1}

    monkeypatch.setattr(runner, "_execute", execute)
    result = await runner.compile(SOURCE, "bpp", target=stage)
    assert calls == ["compile-json"]
    assert result["success"]
    assert result[stage][field] == []


@pytest.mark.parametrize("exit_code,failure_reason", [(1, None), (0, "output_limit")])
@pytest.mark.asyncio
async def test_compile_json_native_error_stops_before_graph_analysis(monkeypatch, exit_code, failure_reason):
    runner = DockerCompilerRunner()
    calls = []

    async def execute(**kwargs):
        calls.append(kwargs["mode"])
        return {"exit_code": exit_code, "failure_reason": failure_reason,
                "stdout": "", "stderr": "[ERROR] invalid program", "execution_time": 1}

    monkeypatch.setattr(runner, "_execute", execute)
    result = await runner.compile(SOURCE, "bpp")
    assert calls == ["compile-json"]
    assert not result["success"]
    assert not any(stage in result for stage in ("ast", "ir", "ssa", "asm"))


@pytest.mark.asyncio
async def test_unsupported_compile_json_image_fails_closed_without_graph_fallback(monkeypatch):
    runner = DockerCompilerRunner()
    calls = []

    async def execute(**kwargs):
        calls.append(kwargs["mode"])
        assert kwargs["mode"] == "compile-json"
        return {
            "exit_code": 2,
            "stdout": "",
            "stderr": "[ERROR] unsupported compiler mode: compile-json",
            "execution_time": 1,
        }

    monkeypatch.setattr(runner, "_execute", execute)
    result = await runner.compile(SOURCE, "bpp", target="all")

    assert calls == ["compile-json"]
    assert not result["success"]
    assert not any(stage in result for stage in ("ast", "ir", "ssa", "asm"))


@pytest.mark.parametrize("stage,view", [
    ("ast", {"nodes": [None], "edges": []}),
    ("ssa", {"ssa": {"functions": [None]}}),
    ("ir", {"ssa": {"stage": "ir", "functions": [None]}}),
    ("ir", {"instructions": [None]}),
    ("asm", {"asm": {"lines": [None]}}),
])
def test_malformed_collections_are_not_valid_empty_views(stage, view):
    assert build_bpp_pipeline_from_json(json.dumps({"views": {stage: view}}), SOURCE, "main.bpp", {stage}) is None


@pytest.mark.asyncio
async def test_malformed_unified_ir_keeps_dedicated_fallback(monkeypatch):
    runner = DockerCompilerRunner()
    calls = []

    async def execute(**kwargs):
        mode = kwargs["mode"]
        calls.append(mode)
        payload = {"views": {"ir": {"ssa": {"stage": "ir", "functions": [None]}}}}
        if mode == "dump-ir-json":
            payload = _nested_ir_view()
        return {"exit_code": 0, "stdout": json.dumps(payload), "stderr": "", "execution_time": 1}

    monkeypatch.setattr(runner, "_execute", execute)
    result = await runner.compile(SOURCE, "bpp", target="ir")
    assert calls == ["compile-json", "dump-ir-json"]
    assert result["ir"]["instructions"][-1]["sourceRanges"]
