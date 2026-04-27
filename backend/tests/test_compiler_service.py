import pytest

from app.services.compiler import DockerCompilerRunner


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
