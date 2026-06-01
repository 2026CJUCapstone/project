import json

import pytest

from app.services.compiler import DockerCompilerRunner
from app.services.compiler_graphs import build_bpp_asm_from_json, build_bpp_pipeline_from_json


def test_resolve_filename_uses_java_public_class_name():
    runner = DockerCompilerRunner()

    filename = runner._resolve_filename(
        "java",
        """
        public class HelloWorld {
            public static void main(String[] args) {}
        }
        """,
    )

    assert filename == "HelloWorld.java"


def test_resolve_filename_falls_back_to_main_for_java_without_class():
    runner = DockerCompilerRunner()

    filename = runner._resolve_filename("java", "/* no class here */")

    assert filename == "Main.java"


def test_parse_bpp_diagnostics_extracts_line_and_column():
    runner = DockerCompilerRunner()

    diagnostics = runner._parse_diagnostics(
        "[ERROR] syntax error at line 7, column 13: unexpected token",
        "bpp",
        success=False,
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].severity == "error"
    assert diagnostics[0].line == 7
    assert diagnostics[0].column == 13
    assert "unexpected token" in diagnostics[0].message


def test_parse_bpp_bracketed_parse_diagnostics_keeps_specific_error():
    runner = DockerCompilerRunner()

    diagnostics = runner._parse_diagnostics(
        "[ERROR] Expected ';' after import\n"
        "\n"
        "[ERROR][parse][P1001] Unexpected token\n"
        "  --> 1:13 near `,`\n"
        "  expected: ';'\n"
        "  got: ',' ,\n"
        "[ERROR][parse][P1680] parse failed\n"
        "[NOTE] error count: 1\n"
        "[ERROR][parse][P1001] Unexpected token\n"
        "  --> 1:13 near `,`\n"
        "  expected: ';'\n"
        "  got: ',' ,\n"
        "[ERROR][parse][P1680] parse failed\n"
        "[NOTE] error count: 1\n"
        "[ERROR] failed to load module: /tmp/bpp_run_yAD6vz/src/user/main.bpp\n"
        "[ERROR] compiler pipeline completed with diagnostics (total 1 error(s))\n",
        "bpp",
        success=False,
    )

    assert [(d.line, d.column, d.message, d.code) for d in diagnostics] == [
        (1, 1, "Expected ';' after import", None),
        (1, 13, "Unexpected token", "P1001"),
    ]


def test_parse_python_fallback_uses_traceback_line_number():
    runner = DockerCompilerRunner()

    diagnostics = runner._parse_diagnostics(
        'Traceback (most recent call last):\n'
        '  File "/workspace/main.py", line 9, in <module>\n'
        "SyntaxError: invalid syntax\n",
        "python",
        success=False,
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].severity == "error"
    assert diagnostics[0].line == 9
    assert diagnostics[0].column == 1
    assert diagnostics[0].message == "SyntaxError: invalid syntax"


def test_parse_javascript_fallback_uses_reported_line_number():
    runner = DockerCompilerRunner()

    diagnostics = runner._parse_diagnostics(
        "/workspace/main.js:12\nReferenceError: x is not defined\n",
        "javascript",
        success=False,
    )

    assert len(diagnostics) == 1
    assert diagnostics[0].severity == "error"
    assert diagnostics[0].line == 12
    assert diagnostics[0].column == 1
    assert diagnostics[0].message == "ReferenceError: x is not defined"


def test_build_bpp_asm_from_json_preserves_source_ranges():
    result = build_bpp_asm_from_json(
        json.dumps(
            {
                "asm": {
                    "lines": [
                        {
                            "text": "    mov rax, 0",
                            "instruction": "mov",
                            "operands": ["rax", "0"],
                            "sourceRanges": [
                                {
                                    "file": "main.bpp",
                                    "rangeId": "range-1",
                                    "astNodeId": "ast-1",
                                    "originNodeId": "ast-1",
                                    "startLine": 4,
                                    "startColumn": 5,
                                    "endLine": 4,
                                    "endColumn": 20,
                                    "startOffset": 42,
                                    "endOffset": 57,
                                }
                            ],
                            "generated": False,
                            "generatedReason": "",
                            "ssaInstructionIds": ["ssa-1"],
                            "segments": [{"start": 4, "end": 12}],
                        }
                    ]
                }
            }
        )
    )

    assert result == {
        "lines": [
            {
                "address": "",
                "label": None,
                "instruction": "mov",
                "operands": ["rax", "0"],
                "comment": None,
                "text": "    mov rax, 0",
                "sourceRanges": [
                    {
                        "file": "main.bpp",
                        "rangeId": "range-1",
                        "astNodeId": "ast-1",
                        "originNodeId": "ast-1",
                        "startLine": 4,
                        "startColumn": 5,
                        "endLine": 4,
                        "endColumn": 20,
                        "startOffset": 42,
                        "endOffset": 57,
                    }
                ],
                "generated": False,
                "generatedReason": "",
                "ssaInstructionIds": ["ssa-1"],
                "segments": [{"start": 4, "end": 12}],
            }
        ]
    }
    assert build_bpp_asm_from_json("main:\n    ret\n") is None
    filtered = build_bpp_asm_from_json(
        json.dumps(
            {
                "asm": {
                    "lines": [
                        {"text": "std_io__println:", "instruction": "", "operands": [], "sourceRanges": []},
                        {
                            "text": "    ret",
                            "instruction": "ret",
                            "operands": [],
                            "sourceRanges": [
                                {
                                    "file": "/tmp/bpp/src/std/io.bpp",
                                    "startLine": 4,
                                    "startColumn": 5,
                                    "endLine": 4,
                                    "endColumn": 20,
                                }
                            ],
                        },
                        {"text": "main:", "instruction": "", "operands": [], "sourceRanges": []},
                        {
                            "text": "    mov rax, 0",
                            "instruction": "mov",
                            "operands": ["rax", "0"],
                            "sourceRanges": [
                                {
                                    "file": "/tmp/bpp/src/user/main.bpp",
                                    "startLine": 2,
                                    "startColumn": 5,
                                    "endLine": 2,
                                    "endColumn": 14,
                                }
                            ],
                        },
                        {"text": "    ret", "instruction": "ret", "operands": [], "sourceRanges": []},
                    ]
                }
            }
        ),
        "main.bpp",
    )
    assert [line["text"] for line in filtered["lines"]] == ["main:", "    mov rax, 0", "    ret"]


def test_build_bpp_pipeline_from_unified_json_preserves_precise_source_map():
    payload = {
        "schemaVersion": 1,
        "sourceRangeSemantics": {"columnEncoding": "byte", "offsetEncoding": "byte", "endColumn": "exclusive"},
        "views": {
            "ast": {
                "nodes": [
                    {
                        "id": "n0",
                        "kind": "Program",
                        "label": "Program",
                        "sourceRanges": [],
                        "generated": False,
                    },
                    {
                        "id": "n1",
                        "kind": "ReturnStatement",
                        "label": "return 0",
                        "sourceRanges": [
                            {
                                "rangeId": "range-return",
                                "astNodeId": "ast-return",
                                "originNodeId": "ast-return",
                                "file": "/tmp/bpp/src/user/main.bpp",
                                "startLine": 2,
                                "startColumn": 5,
                                "endLine": 2,
                                "endColumn": 14,
                                "startOffset": 26,
                                "endOffset": 35,
                            }
                        ],
                    },
                ],
                "edges": [{"from": "n0", "to": "n1", "label": "body"}],
            },
            "ssa": {
                "ssa": {
                    "functions": [
                        {
                            "id": "ssa-func-0",
                            "name": "main",
                            "blocks": [
                                {
                                    "id": "b0",
                                    "sourceRanges": [],
                                    "generated": True,
                                    "generatedReason": "cfg-block",
                                    "instructions": [
                                        {
                                            "id": "ssa-1",
                                            "opcode": "const",
                                            "result": {"kind": "reg", "id": 1},
                                            "operands": [{"kind": "const", "value": 0}],
                                            "sourceRanges": [
                                                {
                                                    "rangeId": "range-zero",
                                                    "file": "/tmp/bpp/src/user/main.bpp",
                                                    "startLine": 2,
                                                    "startColumn": 12,
                                                    "endLine": 2,
                                                    "endColumn": 13,
                                                    "startOffset": 33,
                                                    "endOffset": 34,
                                                }
                                            ],
                                        },
                                        {
                                            "id": "ssa-2",
                                            "opcode": "jmp",
                                            "result": None,
                                            "operands": [{"kind": "const", "value": 1}],
                                            "sourceRanges": [
                                                {
                                                    "rangeId": "range-return",
                                                    "file": "/tmp/bpp/src/user/main.bpp",
                                                    "startLine": 2,
                                                    "startColumn": 5,
                                                    "endLine": 2,
                                                    "endColumn": 14,
                                                    "startOffset": 26,
                                                    "endOffset": 35,
                                                }
                                            ],
                                        },
                                    ],
                                },
                                {"id": "b1", "sourceRanges": [], "instructions": [{"id": "ssa-3", "opcode": "ret", "operands": []}]},
                            ],
                        },
                        {
                            "id": "ssa-func-1",
                            "name": "std_io__println",
                            "blocks": [{"id": "b0", "sourceRanges": [], "instructions": []}],
                        },
                    ]
                }
            },
            "ir": {
                "ir": {
                    "instructions": [
                        {
                            "id": "ir-1",
                            "opcode": "ret",
                            "operands": ["0"],
                            "sourceRanges": [
                                {
                                    "rangeId": "range-return",
                                    "file": "/tmp/bpp/src/user/main.bpp",
                                    "startLine": 2,
                                    "startColumn": 5,
                                    "endLine": 2,
                                    "endColumn": 14,
                                    "startOffset": 26,
                                    "endOffset": 35,
                                }
                            ],
                        }
                    ]
                }
            },
            "asm": {
                "asm": {
                    "lines": [
                        {"text": "std_io__println:", "instruction": "", "operands": [], "sourceRanges": []},
                        {"text": "main:", "instruction": "", "operands": [], "sourceRanges": [], "generated": True, "generatedReason": "label"},
                        {
                            "text": "    mov rax, 0",
                            "instruction": "mov",
                            "operands": ["rax", "0"],
                            "sourceRanges": [
                                {
                                    "rangeId": "range-zero",
                                    "file": "/tmp/bpp/src/user/main.bpp",
                                    "startLine": 2,
                                    "startColumn": 12,
                                    "endLine": 2,
                                    "endColumn": 13,
                                    "startOffset": 33,
                                    "endOffset": 34,
                                }
                            ],
                            "ssaInstructionIds": ["ssa-1"],
                        },
                    ]
                }
            },
        },
    }

    result = build_bpp_pipeline_from_json(json.dumps(payload), "func main() -> u64 {\n    return 0;\n}\n", "main.bpp")

    assert result is not None
    assert result["sourceRangeSemantics"]["columnEncoding"] == "byte"
    assert result["ast"]["nodes"][1]["sourceRanges"][0]["rangeId"] == "range-return"
    assert result["ast"]["nodes"][1]["sourceLocation"]["column"] == 5
    assert [block["label"] for block in result["ssa"]["blocks"]] == ["main · b0", "main · b1"]
    assert result["ssa"]["blocks"][0]["instructionSourceRanges"][0][0]["startOffset"] == 33
    assert result["ssa"]["edges"] == [{"from": "main:b0", "to": "main:b1", "label": None, "type": "unconditional"}]
    assert result["ir"]["instructions"][0]["sourceRanges"][0]["rangeId"] == "range-return"
    assert [line["text"] for line in result["asm"]["lines"]] == ["main:", "    mov rax, 0"]
    assert result["asm"]["lines"][1]["ssaInstructionIds"] == ["ssa-1"]


@pytest.mark.asyncio
async def test_compile_bpp_all_targets_collects_graph_outputs(monkeypatch: pytest.MonkeyPatch):
    runner = DockerCompilerRunner()
    sample_source = """
    func helper(x: u64) -> u64 {
        if (x > 0) {
            return x + 1;
        }
        return 0;
    }

    func main() -> u64 {
        var value: u64 = helper(4);
        return value;
    }
    """

    async def fake_execute(*, mode: str, source_code: str, language: str, stdin: str = "", optimize: bool = False):
        assert source_code == sample_source
        assert language == "bpp"
        if mode == "compile":
            return {"stdout": "", "stderr": "", "exit_code": 0, "execution_time": 3.5}
        if mode == "json":
            return {"stdout": "", "stderr": "unsupported option", "exit_code": 1, "execution_time": 0.5}
        if mode == "dump-ssa":
            return {
                "stdout": (
                    "func user_tmp_test__helper\n"
                    "b0:\n"
                    "  r1 = param #0\n"
                    "  r2 = const #0\n"
                    "  r3 = ugt r1, r2\n"
                    "  br r3 ? b1 : b2\n"
                    "b1:\n"
                    "  r4 = const #1\n"
                    "  ret r4\n"
                    "b2:\n"
                    "  r5 = const #0\n"
                    "  ret r5\n"
                    "func main\n"
                    "b0:\n"
                    "  r1 = const #4\n"
                    "  r2 = call user_tmp_test__helper(r1)\n"
                    "  ret r2\n"
                ),
                "stderr": "",
                "exit_code": 0,
                "execution_time": 2.0,
            }
        if mode == "dump-ir":
            return {
                "stdout": (
                    "func user_tmp_test__helper\n"
                    "b0:\n"
                    "  r1 = param #0\n"
                    "  ret r1\n"
                    "func main\n"
                    "b0:\n"
                    "  r1 = const #4\n"
                    "  r2 = call user_tmp_test__helper(r1)\n"
                    "  ret r2\n"
                ),
                "stderr": "",
                "exit_code": 0,
                "execution_time": 1.8,
            }
        if mode == "asm":
            return {
                "stdout": (
                    "user_tmp_test__helper:\n"
                    "    push rbp\n"
                    "    mov rbp, rsp\n"
                    ".L0:\n"
                    "    ret\n"
                    "main:\n"
                    "    push rbp\n"
                    "    call user_tmp_test__helper\n"
                    "    ret\n"
                ),
                "stderr": "",
                "exit_code": 0,
                "execution_time": 1.5,
            }
        raise AssertionError(f"unexpected mode: {mode}")

    monkeypatch.setattr(runner, "_execute", fake_execute)

    result = await runner.compile(sample_source, "bpp", optimize=False, target="all")

    assert result["success"] is True
    assert result["ast"] is not None
    assert result["ssa"]["blocks"][0]["label"] == "helper · b0"
    assert result["ssa"]["edges"][0]["type"] == "true"
    assert result["ir"]["instructions"][0]["opcode"] == "helper:"
    assert result["ir"]["instructions"][5]["opcode"] == "main:"
    assert result["asm"]["lines"][0]["label"] == "helper"
    assert result["asm"]["lines"][5]["label"] == "main"


@pytest.mark.asyncio
async def test_compile_bpp_asm_target_uses_json_source_map(monkeypatch: pytest.MonkeyPatch):
    runner = DockerCompilerRunner()
    sample_source = "func main() -> u64 {\n    return 0;\n}\n"

    async def fake_execute(*, mode: str, source_code: str, language: str, stdin: str = "", optimize: bool = False):
        assert source_code == sample_source
        assert language == "bpp"
        if mode == "compile":
            return {"stdout": "", "stderr": "", "exit_code": 0, "execution_time": 3.5}
        if mode == "json":
            return {"stdout": "", "stderr": "unsupported option", "exit_code": 1, "execution_time": 0.5}
        if mode == "asm":
            return {
                "stdout": json.dumps(
                    {
                        "asm": {
                            "lines": [
                                {"text": "std_io__println:", "instruction": "", "operands": [], "sourceRanges": []},
                                {
                                    "text": "    ret",
                                    "instruction": "ret",
                                    "operands": [],
                                    "sourceRanges": [
                                        {
                                            "file": "/tmp/bpp_run/src/std/io.bpp",
                                            "startLine": 2,
                                            "startColumn": 5,
                                            "endLine": 2,
                                            "endColumn": 14,
                                        }
                                    ],
                                },
                                {"text": "main:", "instruction": "", "operands": [], "sourceRanges": []},
                                {
                                    "text": "    mov rax, 0",
                                    "instruction": "mov",
                                    "operands": ["rax", "0"],
                                    "sourceRanges": [
                                        {
                                            "file": "/tmp/bpp_run/src/user/main.bpp",
                                            "startLine": 2,
                                            "startColumn": 5,
                                            "endLine": 2,
                                            "endColumn": 14,
                                        }
                                    ],
                                },
                                {"text": "    ret", "instruction": "ret", "operands": [], "sourceRanges": []},
                            ]
                        }
                    }
                ),
                "stderr": "",
                "exit_code": 0,
                "execution_time": 1.5,
            }
        raise AssertionError(f"unexpected mode: {mode}")

    monkeypatch.setattr(runner, "_execute", fake_execute)

    result = await runner.compile(sample_source, "bpp", optimize=False, target="asm")

    assert result["success"] is True
    assert [line["text"] for line in result["asm"]["lines"]] == ["main:", "    mov rax, 0", "    ret"]
    assert result["asm"]["lines"][1]["sourceRanges"][0]["startLine"] == 2
    assert result["asm"]["lines"][2]["sourceRanges"] == []


@pytest.mark.asyncio
async def test_compile_bpp_uses_unified_json_source_map(monkeypatch: pytest.MonkeyPatch):
    runner = DockerCompilerRunner()
    sample_source = "func main() -> u64 {\n    return 0;\n}\n"
    calls: list[str] = []

    async def fake_execute(*, mode: str, source_code: str, language: str, stdin: str = "", optimize: bool = False):
        calls.append(mode)
        assert source_code == sample_source
        assert language == "bpp"
        if mode == "compile":
            return {"stdout": "", "stderr": "", "exit_code": 0, "execution_time": 3.5}
        if mode == "json":
            return {
                "stdout": json.dumps(
                    {
                        "sourceRangeSemantics": {"columnEncoding": "byte", "offsetEncoding": "byte"},
                        "views": {
                            "ast": {
                                "nodes": [
                                    {"id": "n0", "kind": "Program", "label": "Program", "sourceRanges": []},
                                    {
                                        "id": "n1",
                                        "kind": "ReturnStatement",
                                        "label": "return 0",
                                        "sourceRanges": [
                                            {
                                                "file": "/tmp/bpp/src/user/main.bpp",
                                                "rangeId": "range-return",
                                                "startLine": 2,
                                                "startColumn": 5,
                                                "endLine": 2,
                                                "endColumn": 14,
                                                "startOffset": 26,
                                                "endOffset": 35,
                                            }
                                        ],
                                    },
                                ],
                                "edges": [{"from": "n0", "to": "n1"}],
                            },
                            "ssa": {
                                "ssa": {
                                    "functions": [
                                        {
                                            "name": "main",
                                            "blocks": [
                                                {
                                                    "id": "b0",
                                                    "sourceRanges": [],
                                                    "instructions": [
                                                        {
                                                            "id": "ssa-1",
                                                            "opcode": "ret",
                                                            "operands": [{"kind": "const", "value": 0}],
                                                            "sourceRanges": [
                                                                {
                                                                    "file": "/tmp/bpp/src/user/main.bpp",
                                                                    "startLine": 2,
                                                                    "startColumn": 5,
                                                                    "endLine": 2,
                                                                    "endColumn": 14,
                                                                    "startOffset": 26,
                                                                    "endOffset": 35,
                                                                }
                                                            ],
                                                        }
                                                    ],
                                                }
                                            ],
                                        }
                                    ]
                                }
                            },
                            "ir": {
                                "ir": {
                                    "instructions": [
                                        {
                                            "id": "ir-1",
                                            "opcode": "ret",
                                            "operands": ["0"],
                                            "sourceRanges": [
                                                {
                                                    "file": "/tmp/bpp/src/user/main.bpp",
                                                    "startLine": 2,
                                                    "startColumn": 5,
                                                    "endLine": 2,
                                                    "endColumn": 14,
                                                    "startOffset": 26,
                                                    "endOffset": 35,
                                                }
                                            ],
                                        }
                                    ]
                                }
                            },
                            "asm": {
                                "asm": {
                                    "lines": [
                                        {"text": "main:", "instruction": "", "operands": [], "sourceRanges": []},
                                        {
                                            "text": "    mov rax, 0",
                                            "instruction": "mov",
                                            "operands": ["rax", "0"],
                                            "sourceRanges": [
                                                {
                                                    "file": "/tmp/bpp/src/user/main.bpp",
                                                    "startLine": 2,
                                                    "startColumn": 12,
                                                    "endLine": 2,
                                                    "endColumn": 13,
                                                    "startOffset": 33,
                                                    "endOffset": 34,
                                                }
                                            ],
                                        },
                                    ]
                                }
                            },
                        },
                    }
                ),
                "stderr": "",
                "exit_code": 0,
                "execution_time": 1.5,
            }
        raise AssertionError(f"unexpected mode: {mode}")

    monkeypatch.setattr(runner, "_execute", fake_execute)

    result = await runner.compile(sample_source, "bpp", optimize=False, target="all")

    assert calls == ["compile", "json"]
    assert result["success"] is True
    assert result["ast"]["nodes"][1]["sourceRanges"][0]["rangeId"] == "range-return"
    assert result["ssa"]["blocks"][0]["instructionSourceRanges"][0][0]["startOffset"] == 26
    assert result["ir"]["instructions"][0]["sourceRanges"][0]["startOffset"] == 26
    assert result["asm"]["lines"][1]["sourceRanges"][0]["startOffset"] == 33
    assert result["metadata"]["source_range_semantics"]["columnEncoding"] == "byte"
