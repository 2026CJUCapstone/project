"""Mandatory native-O1 regressions for the installed B++ compiler.

This is a build gate, not contest performance evidence. No downloads, daemon,
credentials, source rewriting, compiler flags from user input or shell commands.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time


CASES={
    'large-local-frame':('''import std.io;
func clobber() -> u64 {
    var scratch: [128]u64;
    var i: u64 = 0;
    while (i < 128) { scratch[i] = 99; i += 1; }
    return scratch[127];
}
func main() -> u64 {
    var values: [8192]u8;
    var i: u64 = 0;
    while (i < 8192) { values[i] = 42; i += 1; }
    var value: u64 = clobber();
    if (value != 99) { return 16; }
    i = 0;
    while (i < 8192) {
        if (values[i] != 42) { return 17; }
        i += 1;
    }
    print_u64(42); print_nl(); return 0;
}
''',b'42\n'),
    'pointer-parameter-gc':('''import std.io;
func read_value(value: *i64) -> i64 { return *value; }
func main() -> u64 {
    var value: i64 = 42;
    print_i64(read_value(&value)); print_nl(); return 0;
}
''',b'42\n'),
}


def check_case(root,name,source,expected,*,compiler='bpp',stdin=b'',optimization='O1',ssa=False):
    if optimization not in ('O0','O1'): raise ValueError('Unsupported regression optimization')
    # The legacy compiler uses the basename in emitted symbol identifiers.
    # Keep diagnostic IDs readable but source module names valid identifiers.
    path=root/(name.replace('-','_')+'.bpp');path.write_text(source,encoding='utf-8')
    assembly=root/(name+'.asm');obj=root/(name+'.o');binary=root/name
    compile_argv=[compiler,'-'+optimization,*(['-dump-ssa'] if ssa else []),'-asm',str(path)]
    row=dict(name=name,sourceSha256=hashlib.sha256(source.encode()).hexdigest(),passed=False,
             compilerArgv=compile_argv,phases=[])
    try:
        for phase,argv,timeout in (
            ('compile',compile_argv,15),
            ('assemble',['nasm','-f','elf64','-O1',str(assembly),'-o',str(obj)],5),
            ('link',['ld',str(obj),'-o',str(binary)],5),
            ('run',[str(binary)],2),
        ):
            started=time.monotonic()
            result=subprocess.run(argv,input=stdin if phase=='run' else b'',capture_output=True,timeout=timeout)
            row['phases'].append(dict(phase=phase,argv=argv,exitCode=result.returncode,
                wallSeconds=round(time.monotonic()-started,6),stdoutBytes=len(result.stdout),
                stdoutSha256=hashlib.sha256(result.stdout).hexdigest(),stderrBytes=len(result.stderr)))
            if result.returncode!=0:
                return {**row,'phase':phase,'exitCode':result.returncode,
                    'diagnostic':result.stderr[:4096].decode(errors='replace')}
            if phase=='compile':
                if not result.stdout or len(result.stdout)>4*1024**2:
                    return {**row,'phase':phase,'error':'Invalid assembly size'}
                assembly.write_bytes(result.stdout)
                row['assemblySha256']=hashlib.sha256(result.stdout).hexdigest()
                if name.startswith('pointer-parameter-gc'):
                    row['gcRemovalLabelPresent']=b'std_mem__bpp_gc_root_slot_remove:' in result.stdout.splitlines()
                    if not row['gcRemovalLabelPresent']:
                        return {**row,'phase':phase,'error':'Missing GC root-slot removal label'}
            elif phase=='assemble' and obj.is_file():
                row['objectSha256']=hashlib.sha256(obj.read_bytes()).hexdigest()
            elif phase=='link' and binary.is_file():
                row['binarySha256']=hashlib.sha256(binary.read_bytes()).hexdigest()
            elif phase=='run' and result.stdout!=expected:
                return {**row,'phase':phase,'error':'Unexpected output',
                    'stdout':result.stdout[:4096].decode(errors='replace')}
        return {**row,'passed':True}
    except subprocess.TimeoutExpired:
        return {**row,'phase':phase,'error':'Bounded regression timed out'}
    except OSError as exc:
        return {**row,'phase':phase,'error':type(exc).__name__}


def main():
    with tempfile.TemporaryDirectory(prefix='bpp-runtime-regression-') as folder:
        rows=[check_case(Path(folder),name,source,expected) for name,(source,expected) in CASES.items()]
    print(json.dumps(dict(scope='B++ native-O1 build regressions; NOT performance approval',results=rows)),flush=True)
    return 0 if all(row['passed'] for row in rows) else 1


if __name__=='__main__': raise SystemExit(main())
