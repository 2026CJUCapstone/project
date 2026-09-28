"""Frozen bounded-tar-v1 collector and safe artifact extraction.

Keep this module byte-for-byte stable for historical measured receipts. A changed
artifact format needs a new module and contract ID, never a mutation here.
"""
import io
from pathlib import Path, PurePosixPath
import re
import tarfile
import unicodedata


ARTIFACT_BYTES=8*1024**2
ARCHIVE_BYTES=ARTIFACT_BYTES+1024**2
MAX_FILES=512


def artifact_archive_script_v1(root='/work/artifact'):
    """Fixed collector, executed only after the compiled process tree is reaped."""
    return (f"import io,os,stat,sys,tarfile;root={root!r};total=0;items=[]\n"
        "for base,dirs,files in os.walk(root,followlinks=False):\n"
        " for name in dirs+files:\n"
        "  path=os.path.join(base,name);s=os.lstat(path)\n"
        "  if not (stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)): raise ValueError('nonregular')\n"
        "  total+=s.st_size if stat.S_ISREG(s.st_mode) else 0;items.append(path)\n"
        f"  if total>{ARTIFACT_BYTES} or len(items)>{MAX_FILES}: raise ValueError('oversized')\n"
        "buf=io.BytesIO()\n"
        "with tarfile.open(fileobj=buf,mode='w',format=tarfile.PAX_FORMAT) as t:\n"
        " for path in items:\n"
        "  info=t.gettarinfo(path,arcname=os.path.relpath(path,root));info.mtime=0;info.uid=0;info.gid=0;info.uname='';info.gname=''\n"
        "  if info.isfile():\n"
        "   with open(path,'rb') as source: t.addfile(info,source)\n"
        "  else: t.addfile(info)\n"
        "sys.stdout.buffer.write(buf.getvalue())")


def unpack_artifact_v1(data,destination,language):
    """No extractall: reject traversal, links, devices, collisions and tar bombs."""
    if len(data)>ARCHIVE_BYTES: raise ValueError('Oversized artifact archive')
    files={}; total=0; seen=set(); directories=set(); portable_paths={}
    destination=Path(destination)
    if destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
        raise ValueError('Fresh empty artifact directory required')
    with tarfile.open(fileobj=io.BytesIO(data),mode='r:') as archive:
        for member in archive:
            if archive.pax_headers: raise ValueError('Global artifact metadata is forbidden')
            raw=member.name
            if raw in ('.','./') and member.isdir(): continue
            name=raw[2:] if raw.startswith('./') else raw
            if member.isdir(): name=name.rstrip('/')
            path=PurePosixPath(name)
            # Java class/package identifiers may contain Unicode. Preserve their
            # exact bytes; never normalize/rename an artifact on the worker.
            # PAX is needed for Unicode and long leaf names, but only its path
            # extension is allowed, subjected to every ordinary path check.
            if (not name or len(name.encode('utf-8',errors='strict'))>240 or '\\' in name or ':' in name
                    or path.is_absolute() or any(p in ('','..','.') for p in name.split('/'))
                    or any(p.endswith('.') or re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?',p) for p in path.parts)
                    or set(member.pax_headers)-{'path'}
                    or ('path' in member.pax_headers and member.pax_headers['path']!=raw)
                    or name in seen
                    or any(c not in '_.$/-' and unicodedata.category(c)[0] not in 'LMN'
                           and unicodedata.category(c) not in ('Sc','Pc') for c in name)):
                raise ValueError('Invalid artifact path')
            # Reject aliases on case-insensitive/normalizing host filesystems,
            # including implicit parent directories, before writing any bytes.
            for end in range(1,len(path.parts)+1):
                prefix='/'.join(path.parts[:end])
                key=unicodedata.normalize('NFC',prefix).casefold()
                previous=portable_paths.setdefault(key,prefix)
                if previous!=prefix: raise ValueError('Ambiguous artifact path')
            seen.add(name)
            if len(seen)>MAX_FILES: raise ValueError('Too many artifact entries')
            if member.isdir():
                directories.add(name)
                continue
            if not member.isfile() or member.size<0: raise ValueError('Nonregular artifact entry')
            allowed=(name.endswith('.class') if language=='java' else
                name=={'python':'main.pyc','javascript':'main.js'}.get(language,'program'))
            if not allowed: raise ValueError('Unexpected artifact file')
            total+=member.size
            if total>ARTIFACT_BYTES: raise ValueError('Artifact byte cap exceeded')
            content=archive.extractfile(member).read(member.size+1)
            if len(content)!=member.size: raise ValueError('Truncated artifact')
            files[name]=content
    required={'java':'Main.class','python':'main.pyc','javascript':'main.js'}.get(language,'program')
    if required not in files: raise ValueError('Missing entry artifact')
    # Check file/directory collisions before any filesystem write.
    for name in files:
        if name in directories or any(str(p) in files for p in PurePosixPath(name).parents if str(p)!='.'):
            raise ValueError('Artifact file/directory collision')
    for name in directories:
        if any(str(p) in files for p in PurePosixPath(name).parents if str(p)!='.'):
            raise ValueError('Artifact file/directory collision')
    for name,content in files.items():
        path=destination.joinpath(*PurePosixPath(name).parts)
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as output: output.write(content)
        path.chmod(0o555 if name=='program' else 0o444)
