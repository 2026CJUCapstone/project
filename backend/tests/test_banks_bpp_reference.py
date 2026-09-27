"""Trusted authored J reference: Windows B++ correctness, not resource evidence."""
from pathlib import Path
import random

import pytest

from tests.test_freshman_bpp_a_d_sources import (
    COMPILE_TIMEOUT_SECONDS, RUN_TIMEOUT_SECONDS, SOURCE_DIRECTORY,
    _compile_to_assembly, _configured_toolchain, _run, _statement_examples,
)
from tools.freshman_contest.banks import generate, solve


def test_banks_bpp_source_exists():
    assert (SOURCE_DIRECTORY/'J.bpp').is_file()


def test_banks_bpp_matches_floor_large_and_seeded_reference_cases(tmp_path: Path):
    toolchain=_configured_toolchain()
    if toolchain is None: pytest.skip('Explicit local Windows B++ toolchain required; no installation')
    compiler,compiler_root,nasm,linker,kernel32=toolchain
    assembly=tmp_path/'banks.asm';obj=tmp_path/'banks.obj';executable=tmp_path/'banks.exe'
    _compile_to_assembly(compiler,compiler_root,SOURCE_DIRECTORY/'J.bpp',assembly)
    compiled=_run([str(nasm),'-f','win64','-O1',str(assembly),'-o',str(obj)],
                  cwd=compiler_root,input_text=None,timeout=COMPILE_TIMEOUT_SECONDS)
    assert compiled.returncode==0,compiled.stderr.decode(errors='replace')
    linked=_run([str(linker),'/nologo','/Brepro','/subsystem:console','/entry:mainCRTStartup',
                 f'/out:{executable}',str(obj),str(kernel32)],
                cwd=compiler_root,input_text=None,timeout=COMPILE_TIMEOUT_SECONDS)
    assert linked.returncode==0,linked.stderr.decode(errors='replace')
    cases=_statement_examples('J')
    for seed in (0,73,1926): cases.extend((text,solve(text)) for text in generate(seed))
    rng=random.Random(10350)
    for _ in range(50):
        count=rng.randrange(2,35)
        values=[rng.randrange(-100,101) for _ in range(count-1)]
        values.append(1-sum(values))
        text=f'{count}\n'+' '.join(map(str,values))+'\n'
        cases.append((text,solve(text)))
    for text in ('3\n-7 3 7\n','4\n-15 5 8 6\n','+3\r\n-7\t+3 +7\n'):
        cases.append((text,solve(text)))
    assert len(cases)==90
    assert max(int(expected) for _,expected in cases)>2**31
    for text,expected in cases:
        result=_run([str(executable)],cwd=tmp_path,input_text=text,timeout=RUN_TIMEOUT_SECONDS)
        assert result.returncode==0,result.stderr.decode(errors='replace')
        assert result.stdout.decode().strip()==expected,repr(text[:200])
