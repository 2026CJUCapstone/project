"""Fixed-source G codegen diagnosis inside a disposable, bounded container.

The assembly-only experiment below is NOT a compiler fix or policy evidence.
No source rewrite is performed. Output records both original and modified hash.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    source=Path('/source/G.bpp')
    result=subprocess.run(['bpp','-O1','-asm',str(source)],capture_output=True,timeout=12)
    assert result.returncode==0, result.stderr[:4096]
    assert len(result.stdout)<4*1024**2
    assembly=result.stdout.decode()
    # Restrict the experimental substitution to main's one prologue.
    match=re.search(r'^main:\s*\n',assembly,re.M)
    assert match is not None, 'Missing main label'
    tail=assembly[match.end():]
    prologue=re.match(r'(\s*push rbp\s*\n\s*mov rbp, rsp\s*\n\s*sub rsp, )(\d+)',tail)
    assert prologue is not None, tail[:500]
    old_size=int(prologue.group(2))
    assert old_size==2048, 'Not the known fixed-frame compiler; re-diagnose'
    patched=assembly[:match.end()]+prologue.group(1)+'16384'+tail[prologue.end():]
    observations=[]
    for name,text in [('original',assembly),('main-frame-only-16384',patched)]:
        asm=Path('/work')/(name+'.asm'); asm.write_text(text)
        obj=Path('/work')/(name+'.o'); binary=Path('/work')/name
        subprocess.run(['nasm','-f','elf64','-O1',str(asm),'-o',str(obj)],check=True,capture_output=True,timeout=5)
        subprocess.run(['ld',str(obj),'-o',str(binary)],check=True,capture_output=True,timeout=5)
        row=dict(name=name,assemblySha256=sha(text.encode()))
        try:
            run=subprocess.run([str(binary)],input=b'1\n1000\n',capture_output=True,timeout=1)
            row.update(exitCode=run.returncode,stdout=run.stdout[:1024].decode(errors='replace'),
                       stderr=run.stderr[:1024].decode(errors='replace'),timeout=False)
        except subprocess.TimeoutExpired as exc:
            row.update(timeout=True,stdout=(exc.stdout or b'')[:1024].decode(errors='replace'))
        observations.append(row)
    print(json.dumps(dict(scope='assembly-only root-cause experiment; NOT compiler fix or measured acceptance',
        sourceSha256=sha(source.read_bytes()),compilerCommand=['bpp','-O1','-asm','/source/G.bpp'],
        originalStackReserve=old_size,mainPrefix=tail[:450],
        mainRbpOffsets=sorted({int(n) for n in re.findall(r'\[rbp\s*-\s*(\d+)\]',tail)})[-20:],
        observations=observations)),flush=True)


if __name__=='__main__': main()
