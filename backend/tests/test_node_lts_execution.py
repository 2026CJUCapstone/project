"""Opt-in Node binary smoke: not a Linux sandbox isolation or judge test."""
import os
from pathlib import Path
import subprocess

import pytest


pytestmark = pytest.mark.skipif(not os.getenv('TEST_NODE24_EXECUTABLE'),
    reason='explicit dedicated Node24 binary required')


@pytest.fixture
def node():
    binary = Path(os.environ['TEST_NODE24_EXECUTABLE'])
    assert binary.is_absolute() and binary.is_file()
    version = subprocess.run([str(binary), '--version'], capture_output=True, timeout=5, check=True)
    assert version.stdout.strip() == b'v24.21.0'
    return str(binary)


@pytest.mark.parametrize('code,stdin,expected', [
    ('console.log("Hello, World!");', b'', b'Hello, World!\n'),
    ('const fs=require("fs"); console.log(fs.readFileSync(0,"utf8").trim().split(/\\s+/).map(Number).reduce((a,b)=>a+b,0));',
        b'40 2\r\n', b'42\n'),
    ('const fs=require("node:fs"); process.stdout.write(fs.readFileSync(0,"utf8"));',
        '한글 입력\n'.encode(), '한글 입력\n'.encode()),
    ('console.log((9007199254740993n+7n).toString());', b'', b'9007199254741000\n'),
])
def test_javascript_examples_check_and_execute(node, tmp_path, code, stdin, expected):
    source = tmp_path / 'main.js'
    source.write_text(code, encoding='utf-8')
    compile_result = subprocess.run([node, '--check', str(source)], capture_output=True, timeout=5)
    assert compile_result.returncode == 0, compile_result.stderr.decode(errors='replace')
    result = subprocess.run([node, str(source)], input=stdin, capture_output=True, timeout=5)
    assert result.returncode == 0
    assert result.stdout.replace(b'\r\n', b'\n') == expected
    assert result.stderr == b''


def test_syntax_error_remains_distinct_from_runtime_error(node, tmp_path):
    source = tmp_path / 'main.js'
    source.write_text('const broken = ;', encoding='utf-8')
    compile_result = subprocess.run([node, '--check', str(source)], capture_output=True, timeout=5)
    assert compile_result.returncode != 0
    assert b'SyntaxError' in compile_result.stderr
    source.write_text('throw new Error("fixture runtime failure");', encoding='utf-8')
    assert subprocess.run([node, '--check', str(source)], capture_output=True, timeout=5).returncode == 0
    result = subprocess.run([node, str(source)], capture_output=True, timeout=5)
    assert result.returncode != 0 and b'fixture runtime failure' in result.stderr
