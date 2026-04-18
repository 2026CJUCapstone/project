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
