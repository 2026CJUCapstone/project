"""Trusted, fixed-commit native compiler experiment, not an installed runtime.

Run only in the bounded one-off host harness. No network or Docker socket.
The artifact is a candidate, never silently promoted to an approved image.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import tarfile
import time
from functools import partial

COMMIT='9859a2dc783c9346be2ab9447e1569218bcc5093'
ARCHIVE_SHA='010e9abd3e2469b6bd1b4ee006ed142e695ecf8ee8af0b81b62fac764d2355bf'
BASELINE_SHA='1dcc9ac5ace81fae5ec846d87064326a038f8adb700adb5f61386b26cc4002f4'
BASELINE_COMMIT='2d596233f45973394a5d951c40b11f78171c8870'
BOOTSTRAP=Path('/usr/local/libexec/bpp/v13_stage1')
MODES=('selfhost','frontend','frontend-reduction','stage0','regressions','fixedpoint')
STAGE0_SHA='2e29c5077bd1a7b299ea1d06e80dcb871429a594c92bc79fac57121be19dff6a'
STAGE2_SHA='7f4864362863ddc9daa687d221387e9f2612220521f89e8a9e05b2e3f40b4a23'
REFERENCE_SHA={
    'G':'621021dbfce96ffc3f3b3e7d3a0ab5c24b41bfe439e7effd389d8d2be56b9610',
    'J':'74bf3e8f2fd8074474afee58103e1db4355f03003ff30b7eb6708e7335e7f2f6',
}


def candidate_regressions(root):
    import importlib.util
    candidate=Path('/input/stage0')
    if candidate.read_bytes()[:4]!=b'\x7fELF' or sha(candidate) not in (STAGE0_SHA,STAGE2_SHA):
        raise ValueError('Unreviewed stage0 binary')
    spec=importlib.util.spec_from_file_location('candidate_gate','/input/verify_bpp_runtime.py')
    gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
    cases=[]
    for name,(source,expected) in gate.CASES.items():
        for optimization in ('O0','O1'):
            cases.append((name+'-'+optimization,source,expected,b'',optimization,False))
        if name=='pointer-parameter-gc':
            for optimization in ('O0','O1'):
                cases.append((name+'-ssa-'+optimization,source,expected,b'',optimization,True))
    for label,stdin,expected in [('G',b'1\n1000\n',b'1000\n'),('J',b'3\n-5 4 3\n',b'5\n')]:
        source=Path('/input')/(label+'.bpp')
        if sha(source)!=REFERENCE_SHA[label]: raise ValueError('Unreviewed reference source')
        cases.append(('reference_'+label,source.read_text(encoding='utf-8'),expected,stdin,'O1',False))
    rows=[]
    for name,source,expected,stdin,optimization,ssa in cases:
        row=gate.check_case(root/'src',name,source,expected,compiler=str(candidate),stdin=stdin,
                            optimization=optimization,ssa=ssa)
        row.update(stdinSha256=hashlib.sha256(stdin).hexdigest(),expectedSha256=hashlib.sha256(expected).hexdigest())
        rows.append(row)
    return rows


def frontend_reductions():
    # Fixed trusted controls, not a workaround for compiler source or references.
    return [('empty','func main() -> u64 { return 0; }\n'),
            ('annotations','import compiler.annotations;\nfunc main() -> u64 { return 0; }\n')]


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def verified_stage0(path):
    if path.read_bytes()[:4]!=b'\x7fELF' or sha(path)!=STAGE0_SHA:
        raise ValueError('Unreviewed stage0 binary')
    return str(path)


def fixed_point(assembly_root,binary_root):
    return dict(fixedPoint=sha(binary_root/'stage1')==sha(binary_root/'stage2'),
                assemblyFixedPoint=sha(assembly_root/'stage1.asm')==sha(assembly_root/'stage2.asm'))


def canonical_assembly(source,root):
    # NASM retains the input pathname as an ELF file symbol. Compare builds with
    # the same assembler input name; retain each original ASM unchanged as evidence.
    target=root/'native.asm'
    shutil.copyfile(source,target)
    if sha(source)!=sha(target): raise RuntimeError('Assembly copy identity mismatch')
    return target


def extract_candidate(archive,target):
    if sha(archive) not in (ARCHIVE_SHA,BASELINE_SHA): raise ValueError('Unreviewed compiler source archive')
    with tarfile.open(archive,'r:gz') as stream:
        members=stream.getmembers()
        if len(members)>1000 or sum(m.size for m in members)>16*1024**2:
            raise ValueError('Source archive cap')
        for member in members:
            path=Path(member.name)
            if (path.is_absolute() or '..' in path.parts or not path.parts
                    or path.parts[0] not in ('src','config.ini')
                    or not (member.isfile() or member.isdir())):
                raise ValueError('Unsafe source archive')
        stream.extractall(target,filter='data')


def child_limits(cpu_seconds=100):
    import resource
    resource.setrlimit(resource.RLIMIT_FSIZE,(32*1024**2,32*1024**2))
    resource.setrlimit(resource.RLIMIT_CPU,(cpu_seconds,cpu_seconds))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))


def build_phase(rows,root,label,argv,output,timeout,*,cpu_seconds=100):
    # CPU accounting distinguishes a build budget stop from semantic failure.
    import resource
    before=resource.getrusage(resource.RUSAGE_CHILDREN)
    error=root/(label+'.stderr');started=time.monotonic()
    if cpu_seconds not in (100,600): raise ValueError('Unreviewed phase CPU budget')
    row=dict(phase=label,argv=argv,timeoutSeconds=timeout,cpuBudgetSeconds=cpu_seconds)
    with output.open('xb') as stdout,error.open('xb') as stderr:
        try:
            run=subprocess.run(argv,cwd=root,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,
                timeout=timeout,preexec_fn=child_limits if cpu_seconds==100 else partial(child_limits,cpu_seconds))
            row['exitCode']=run.returncode
        except subprocess.TimeoutExpired:
            row['timedOut']=True
    row.update(wallSeconds=round(time.monotonic()-started,3),stdoutBytes=output.stat().st_size,
        stdoutSha256=sha(output),stderrBytes=error.stat().st_size,
        diagnostic=error.read_bytes()[:4096].decode(errors='replace'))
    after=resource.getrusage(resource.RUSAGE_CHILDREN)
    row['cpuSeconds']=round(after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,3)
    rows.append(row);print(json.dumps(row),flush=True)
    if row.get('exitCode')!=0: raise RuntimeError('Native compiler candidate phase failed: '+label)


def frontend_argv(bootstrap,source):
    return [str(bootstrap),'-dump-ast','--ast-no-std','--ast-func','main',str(source)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=MODES,default='selfhost')
    args=parser.parse_args()
    root=Path('/work/candidate');root.mkdir()
    archive=Path('/input/compiler.tar.gz');rows=[]
    report=dict(scope='bounded native compiler candidate, NOT approved image or contest acceptance',
        mode=args.mode,commit=BASELINE_COMMIT if sha(archive)==BASELINE_SHA else COMMIT,
        sourceArchiveSha256=sha(archive),phases=rows,passed=False)
    try:
        if BOOTSTRAP.read_bytes()[:4]!=b'\x7fELF': raise RuntimeError('Native ELF bootstrap required')
        report['bootstrapBinarySha256']=sha(BOOTSTRAP)
        extract_candidate(archive,root)
        (root/'bpp.toml').write_text('version=v13\nmodule_root=src\nstd_root=src\nnasm_path=/usr/bin/nasm\nld_path=/usr/bin/ld\n')
        previous=str(BOOTSTRAP)
        if args.mode=='regressions':
            if sha(archive)!=ARCHIVE_SHA: raise ValueError('Candidate regressions require candidate standard library')
            child_limits()
            report['candidateBinarySha256']=sha(Path('/input/stage0'))
            report['candidateStage']=2 if report['candidateBinarySha256']==STAGE2_SHA else 0
            report['gateScriptSha256']=sha(Path('/input/verify_bpp_runtime.py'))
            report['regressions']=candidate_regressions(root)
            if not all(row['passed'] for row in report['regressions']):
                raise RuntimeError('Candidate native-O1 regressions failed')
        if args.mode=='frontend':
            build_phase(rows,root,'frontend-analysis',frontend_argv(BOOTSTRAP,root/'src/main.bpp'),root/'frontend.out',120)
            report['frontendCompleted']=True
            report['compiledExecutable']=False
        if args.mode=='frontend-reduction':
            report['compiledExecutable']=False
            for name,source in frontend_reductions():
                source_path=root/'src'/('probe_'+name+'.bpp')
                with source_path.open('x',encoding='utf-8') as file: file.write(source)
                report.setdefault('controls',[]).append(dict(name=name,sourceSha256=sha(source_path)))
                build_phase(rows,root,name+'-analysis',frontend_argv(BOOTSTRAP,source_path),root/(name+'.out'),120)
            report['frontendCompleted']=True
        if args.mode=='fixedpoint':
            if sha(archive)!=ARCHIVE_SHA: raise ValueError('Fixed point requires candidate standard library')
            previous=verified_stage0(Path('/input/stage0'))
            report['candidateBinarySha256']=STAGE0_SHA
        stages=range(1,3) if args.mode=='fixedpoint' else range(3 if args.mode=='selfhost' else 1 if args.mode=='stage0' else 0)
        extended=args.mode in ('stage0','fixedpoint')
        for stage in stages:
            name=f'stage{stage}'
            assembly=(Path('/output') if extended else root)/(name+'.asm')
            obj=root/(name+'.o');binary=Path('/output')/name
            build_phase(rows,root,name+'-compile',[previous,'-asm',str(root/'src/main.bpp')],assembly,
                660 if extended else 120,cpu_seconds=600 if extended else 100)
            nasm_source=canonical_assembly(assembly,root) if args.mode=='fixedpoint' else assembly
            build_phase(rows,root,name+'-assemble',['/usr/bin/nasm','-felf64','-O1',str(nasm_source),'-o',str(obj)],root/(name+'-assemble.out'),60 if extended else 20)
            build_phase(rows,root,name+'-link',['/usr/bin/ld',str(obj),'-o',str(binary)],root/(name+'-link.out'),10)
            rows[-1]['binarySha256']=sha(binary)
            previous=str(binary)
        if args.mode=='stage0':
            report.update(compiledExecutable=True,fixedPointVerified=False)
        # Exact fixed point is evidence of bootstrap consistency, not semantic
        # correctness. The native-O1 regressions and references are separate.
        if args.mode in ('selfhost','fixedpoint'):
            asm_root=Path('/output') if args.mode=='fixedpoint' else root
            report.update(fixed_point(asm_root,Path('/output')))
            if not report['fixedPoint'] or not report['assemblyFixedPoint']: raise RuntimeError('Compiler stage1/stage2 differ')
        report['passed']=True
    except Exception as exc:
        report['error']=str(exc)[:1000]
    report['cgroupCounters']={name:Path('/sys/fs/cgroup',name).read_text()[:4096]
        for name in ('cpu.stat','memory.peak','memory.events') if Path('/sys/fs/cgroup',name).is_file()}
    print(json.dumps(report),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__': raise SystemExit(main())
