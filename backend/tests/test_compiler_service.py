import json

import pytest

from app.services.compiler import DockerCompilerRunner
from app.services.compiler_graphs import build_bpp_asm_from_json


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
                                    "startLine": 4,
                                    "startColumn": 5,
                                    "endLine": 4,
                                    "endColumn": 20,
                                }
                            ],
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
                        "startLine": 4,
                        "startColumn": 5,
                        "endLine": 4,
                        "endColumn": 20,
                    }
                ],
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
