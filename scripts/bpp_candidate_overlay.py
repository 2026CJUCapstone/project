"""Fixed, read-only compiler overlay for isolated tests, never image approval.

The base image and installed wrapper remain unchanged. Only compile containers
receive the exact candidate ELF and its own standard library. No product hook.
"""
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile

from probe_bpp_candidate import ARCHIVE_SHA, COMMIT, STAGE2_SHA, extract_candidate

IMAGE='sha256:7a3aa3717f2c62f60ff52f680335ebee414151136d6f836382b1b543a43c5db1'
BINARY_TARGET='/usr/local/libexec/bpp/v13_stage1'
STD_TARGET='/usr/local/share/bpp/src/std'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def plain_bytes(path,cap):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>cap:
        raise ValueError('Bounded plain candidate file required')
    with path.open('rb') as file: data=file.read(cap+1)
    if len(data)>cap: raise ValueError('Candidate file cap')
    return data


def standard_manifest(archive_data):
    if digest(archive_data)!=ARCHIVE_SHA: raise ValueError('Unreviewed compiler archive')
    records={}
    with tarfile.open(fileobj=io.BytesIO(archive_data),mode='r:gz') as archive:
        for member in archive.getmembers():
            if member.isfile() and member.name.startswith('src/std/'):
                data=archive.extractfile(member).read()
                records[member.name[len('src/std/'):]]=digest(data)
    if not records: raise ValueError('Missing candidate standard library')
    return records


def overlay_identity(root):
    overlay=root/'bpp-candidate'
    if overlay.is_symlink() or overlay.resolve()!=overlay:
        raise ValueError('Exact candidate overlay required')
    binary=plain_bytes(overlay/'compiler',32*1024**2)
    if binary[:4]!=b'\x7fELF' or digest(binary)!=STAGE2_SHA:
        raise ValueError('Unreviewed final candidate ELF')
    expected=standard_manifest(plain_bytes(overlay/'compiler.tar.gz',2*1024**2))
    std=overlay/'source/src/std'
    if any(path.is_symlink() or path.resolve()!=path for path in (overlay/'source',overlay/'source/src',std)):
        raise ValueError('Symlink in standard library root')
    actual={}
    for path in std.rglob('*'):
        if path.is_symlink(): raise ValueError('Symlink in candidate standard library')
        if path.is_file(): actual[path.relative_to(std).as_posix()]=digest(plain_bytes(path,2*1024**2))
        elif not path.is_dir(): raise ValueError('Nonregular standard library file')
    if actual!=expected: raise ValueError('Candidate standard library differs from fixed source')
    return dict(kind='isolated-readonly-candidate-overlay',commit=COMMIT,binarySha256=STAGE2_SHA,
        sourceArchiveSha256=ARCHIVE_SHA,standardLibrarySha256=digest(json.dumps(actual,sort_keys=True,separators=(',',':')).encode()),
        mounts=[dict(target=BINARY_TARGET,mode='ro'),dict(target=STD_TARGET,mode='ro')],imageAccepted=False)


def bind_base_identity(identity,image,installed):
    if image!=IMAGE or not re.fullmatch('binary-sha256:[a-f0-9]{64}',installed['version']) or not re.fullmatch('[a-f0-9]{64}',installed['launcherSha256']):
        raise ValueError('Exact base runtime identity required')
    record={**identity,'baseImage':image,'installedBinaryVersion':installed['version'],
            'installedLauncherSha256':installed['launcherSha256']}
    return {**record,'manifestSha256':digest(json.dumps(record,sort_keys=True,separators=(',',':')).encode())}


def prepare_overlay(root):
    overlay=root/'bpp-candidate';overlay.mkdir(mode=0o755)
    archive_data=plain_bytes(root/'compiler.tar.gz',2*1024**2)
    standard_manifest(archive_data)
    with (overlay/'compiler.tar.gz').open('xb') as file: file.write(archive_data)
    packed=plain_bytes(root/'candidate-stage2.gz',8*1024**2)
    with gzip.GzipFile(fileobj=io.BytesIO(packed)) as file: binary=file.read(32*1024**2+1)
    if len(binary)>32*1024**2 or binary[:4]!=b'\x7fELF' or digest(binary)!=STAGE2_SHA:
        raise ValueError('Unreviewed final candidate ELF')
    with (overlay/'compiler').open('xb') as file: file.write(binary)
    source=overlay/'source';source.mkdir()
    extract_candidate(overlay/'compiler.tar.gz',source)
    # No need to expose the rest of the compiler source to a child submission.
    for path in overlay.rglob('*'): path.chmod(0o555 if path.is_dir() or path.name=='compiler' else 0o444)
    return overlay_identity(root)


def attach_overlay(options,root,image):
    """Call only after the ordinary child isolation verifier has succeeded."""
    from app.services.judge_runtime_registry import compile_argv, run_argv
    if image!=IMAGE: raise ValueError('Candidate requires exact existing base image')
    spec=json.loads(options['environment']['JUDGE_PHASE_SPEC'])
    if spec['phase']=='run':
        if spec['argv']!=run_argv('bpp'): raise ValueError('Candidate run command mismatch')
        return options
    if spec['phase']!='compile' or spec['argv']!=compile_argv('bpp'):
        raise ValueError('Candidate compile command mismatch')
    overlay_identity(root)
    overlay=root/'bpp-candidate'
    extra={str(overlay/'compiler'):{'bind':BINARY_TARGET,'mode':'ro'},
           str(overlay/'source/src/std'):{'bind':STD_TARGET,'mode':'ro'}}
    if set(extra)&set(options['volumes']) or {BINARY_TARGET,STD_TARGET}&{m['bind'] for m in options['volumes'].values()}:
        raise ValueError('Candidate mount collision')
    return {**options,'volumes':{**options['volumes'],**extra}}


def verify_overlay_options(options,work,image,owner):
    """Validate the final options sent to Docker, including exact RO additions."""
    from verify_runtime_matrix import verify_child_options
    from app.services.judge_runtime_registry import compile_argv,run_argv
    if image!=IMAGE: raise ValueError('Candidate requires exact existing base image')
    spec=json.loads(options['environment']['JUDGE_PHASE_SPEC'])
    phase=spec['phase']
    if phase not in ('compile','run') or spec['argv']!=(compile_argv if phase=='compile' else run_argv)('bpp'):
        raise ValueError('Unexpected candidate phase command')
    stripped={**options,'volumes':dict(options['volumes'])}
    targets=[]
    if phase=='compile':
        root=work.parent;overlay_identity(root)
        for path,target in ((root/'bpp-candidate/compiler',BINARY_TARGET),(root/'bpp-candidate/source/src/std',STD_TARGET)):
            if stripped['volumes'].pop(str(path),None)!={'bind':target,'mode':'ro'}:
                raise ValueError('Exact read-only candidate mount required')
            targets.append(target)
    verify_child_options(stripped,work,image,owner)
    record=dict(phase=phase,overlayApplied=phase=='compile',readOnlyTargets=targets)
    if phase=='run':
        artifact=next(Path(path) for path,mount in options['volumes'].items() if mount['bind']=='/artifact')
        record.update(artifactSha256=digest(plain_bytes(artifact/'program',32*1024**2)),
                      execution='candidate-compiled/base-image-executed')
    return record


def verify_bindings(bindings,names,manifest,artifact):
    if (len(bindings)!=len(names) or len(bindings)<2 or [b['containerName'] for b in bindings]!=names
            or bindings[0]['phase']!='compile' or bindings[0]['overlayApplied'] is not True
            or bindings[0]['readOnlyTargets']!=[BINARY_TARGET,STD_TARGET]
            or any(b['manifestSha256']!=manifest for b in bindings)):
        raise ValueError('Incomplete candidate compile provenance')
    for binding in bindings[1:]:
        if (binding['phase']!='run' or binding['overlayApplied'] is not False or binding['readOnlyTargets']
                or binding['artifactSha256']!=artifact or binding['execution']!='candidate-compiled/base-image-executed'):
            raise ValueError('Candidate execution provenance mismatch')
