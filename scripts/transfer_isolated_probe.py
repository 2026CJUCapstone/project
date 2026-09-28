"""Transfer fixed test inputs using SSH stdin when legacy scp disconnects.

No credentials, arbitrary targets, remote shell interpolation or overwrites.
Only a pre-created, owned /tmp/webcompiler-launcher-test.* directory is allowed.
"""
import argparse
import hashlib
from pathlib import Path
import re
import shlex
import subprocess


def upload_bytes(root, data, name):
    if not re.fullmatch(r'/tmp/webcompiler-launcher-test\.[A-Za-z0-9]+',root):
        raise ValueError('Exact isolated root required')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',name): raise ValueError('Plain filename required')
    if len(data)>8*1024**2: raise ValueError('Transfer cap')
    digest=hashlib.sha256(data).hexdigest()
    program="""import hashlib,os,pathlib,sys
root=pathlib.Path(sys.argv[1]); target=root/sys.argv[2]
assert root.resolve()==root and root.is_dir() and root.stat().st_uid==os.getuid()
size=int(sys.argv[3]); expected=sys.argv[4]
data=sys.stdin.buffer.read(size+1)
assert len(data)==size and hashlib.sha256(data).hexdigest()==expected
with target.open('xb') as output: output.write(data)
print(target.name,len(data),hashlib.sha256(target.read_bytes()).hexdigest())
"""
    command=shlex.join(['python3','-c',program,root,name,str(len(data)),digest])
    subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-p','10022',
        'vulpo@cuha.cju.ac.kr',command],input=data,check=True,timeout=30)


def upload(root,source,name):
    if source.is_symlink() or not source.is_file():
        raise ValueError('Only a regular fixed test input may be transferred')
    data=source.read_bytes()
    if len(data)>8*1024**2: raise ValueError('Transfer cap')
    if len(data)<=8192:
        return upload_bytes(root,data,name)
    count=(len(data)+8191)//8192
    for index in range(count):
        upload_bytes(root,data[index*8192:(index+1)*8192],f'{name}.part-{index:04d}')
    program="""import hashlib,os,pathlib,sys
root=pathlib.Path(sys.argv[1]); name=sys.argv[2]; count=int(sys.argv[3])
assert root.resolve()==root and root.is_dir() and root.stat().st_uid==os.getuid()
parts=[root/(name+'.part-%04d'%i) for i in range(count)]
assert all(p.is_file() and not p.is_symlink() and p.stat().st_size<=8192 for p in parts)
data=b''.join(p.read_bytes() for p in parts)
assert hashlib.sha256(data).hexdigest()==sys.argv[4]
with (root/name).open('xb') as output: output.write(data)
print(name,len(data),hashlib.sha256((root/name).read_bytes()).hexdigest())
"""
    command=shlex.join(['python3','-c',program,root,name,str(count),hashlib.sha256(data).hexdigest()])
    subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-p','10022',
        'vulpo@cuha.cju.ac.kr',command],check=True,timeout=30)


def fixed_inputs(base,*,draft=False,slow=False,candidate=False):
    if candidate and slow:
        raise ValueError('Candidate overlay is not supported by the slow-comparison suite')
    base=Path(base)
    files={
        'measured-app-source.tar.gz':base/'.deploy/runtime-matrix-source-bpp-v2.tar.gz',
        'freshman-package.tar.gz':base/'.deploy'/(
            'freshman-measurement-package-draft-v2-slow.tar.gz' if slow else
            'freshman-measurement-package-draft-v2.tar.gz' if draft
            else 'freshman-measurement-package-v1.tar.gz'),
        **{name:base/'scripts'/name for name in ('run_isolated_runtime_matrix.py',
            'verify_freshman_measurements.py','verify_freshman_slow.py',
            'verify_runtime_matrix.py','verify_measured_launcher.py')},
    }
    if candidate:
        files.update({
            'compiler.tar.gz':base/'.deploy/bpp-candidate-9859a2d-src.tar.gz',
            'candidate-stage2.gz':base/'.deploy/bpp-candidate-9859a2d-stage2.gz',
            'bpp_candidate_overlay.py':base/'scripts/bpp_candidate_overlay.py',
            'probe_bpp_candidate.py':base/'scripts/probe_bpp_candidate.py',
        })
    return files


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True)
    parser.add_argument('--draft',action='store_true',
                        help='transfer the separate frozen-draft reference package')
    parser.add_argument('--slow',action='store_true',
                        help='transfer the separate diagnostic archive with fixed F/I/J slow sources')
    parser.add_argument('--candidate',action='store_true',
                        help='add the fixed read-only B++ compiler candidate for a reference experiment')
    args=parser.parse_args()
    base=Path(__file__).resolve().parents[1]
    try:
        files=fixed_inputs(base,draft=args.draft,slow=args.slow,candidate=args.candidate)
    except ValueError as exc:
        parser.error(str(exc))
    for name,source in files.items(): upload(args.root,source,name)
