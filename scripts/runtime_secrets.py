#!/usr/bin/env python3
"""Read literal deployment credentials, never execute an env file as a script.

Only credential/mail keys are allowed. Topology, verified source identity and
resource names must be supplied before preflight, not changed between phases.
"""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
import sys


MAX_BYTES=65536
MAIL_KEYS=frozenset(('SMTP_HOST','SMTP_PORT','SMTP_USERNAME','SMTP_PASSWORD','SMTP_FROM','SMTP_STARTTLS'))
ALLOWED_KEYS=frozenset(('WEBCOMPILER_SECRET_KEY','WEBCOMPILER_ADMIN_PASSWORD','WEBCOMPILER_POSTGRES_PASSWORD',
    'SECRET_KEY','ADMIN_PASSWORD','PASSWORD_RESET_BASE_URL','WEBCOMPILER_PASSWORD_RESET_BASE_URL'))|MAIL_KEYS|{
    'WEBCOMPILER_'+name for name in MAIL_KEYS}


class RuntimeSecretsError(ValueError):
    pass


@contextmanager
def private_directory(path):
    if os.name!='posix':
        yield None
        return
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        if info.st_uid!=os.getuid() or info.st_mode&0o022:
            raise RuntimeSecretsError('Runtime secrets directory must be owned and not publicly writable')
        yield fd
        current=path.parent.lstat()
        if ((info.st_dev,info.st_ino)!=(current.st_dev,current.st_ino)
                or not stat.S_ISDIR(current.st_mode) or current.st_mode&0o022):
            raise RuntimeSecretsError('Runtime secrets directory changed')
    finally:
        os.close(fd)


def read_private(source):
    info=os.fstat(source.fileno())
    if (not stat.S_ISREG(info.st_mode) or info.st_size>MAX_BYTES
            or (os.name=='posix' and (info.st_uid!=os.getuid() or info.st_mode&0o077))):
        raise RuntimeSecretsError('Runtime secrets must be a bounded private regular file')
    source.seek(0)
    raw=source.read(MAX_BYTES+1)
    return raw,parse(raw)


def load(path,*,allow_missing=False):
    path=Path(path)
    if path.is_symlink():
        raise RuntimeSecretsError('Runtime secrets must be a private regular file')
    try:
        with private_directory(path) as directory:
            # Opening a FIFO must not wait forever before fstat can reject it.
            flags=os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0)
            fd=os.open(path.name if directory is not None else path,flags,dir_fd=directory)
            with os.fdopen(fd,'rb') as source:
                return read_private(source)[1]
    except FileNotFoundError:
        if allow_missing:
            return {}
        raise RuntimeSecretsError('Runtime secrets file is required') from None


def parse(raw):
    if len(raw)>MAX_BYTES or b'\0' in raw:
        raise RuntimeSecretsError('Runtime secrets exceed the supported literal format')
    try:
        lines=raw.decode('utf-8').splitlines()
        values={}
        for line in lines:
            line=line.strip()
            if not line or line.startswith('#'):
                continue
            if len(line.encode())>4096:
                raise ValueError
            words=shlex.split(line,comments=False,posix=True)
            if words and words[0]=='export':
                words=words[1:]
            if len(words)!=1 or '=' not in words[0]:
                raise ValueError
            key,value=words[0].split('=',1)
            if key not in ALLOWED_KEYS or key in values:
                raise ValueError
            values[key]=value
        return values
    except (ValueError,UnicodeError):
        # Never include the rejected line, key or credential in diagnostics.
        raise RuntimeSecretsError('Only distinct literal credential/mail assignments are allowed in runtime secrets') from None


def validate_deployment(values,environment):
    effective=dict(environment)
    effective.update(values)
    password=effective.get('WEBCOMPILER_POSTGRES_PASSWORD','')
    if not re.fullmatch(r'[A-Za-z0-9_-]{24,128}',password):
        raise RuntimeSecretsError('An explicit URL-safe PostgreSQL credential is required')
    for key,minimum in (('SECRET_KEY',32),('ADMIN_PASSWORD',16)):
        prefixed='WEBCOMPILER_'+key
        value=effective.get(key) or effective.get(prefixed)
        # Only genuinely absent credentials may be generated. Supplied empty
        # or weak credentials are configuration errors, not rotation requests.
        if (key in effective or prefixed in effective) and (not value or len(value)<minimum):
            raise RuntimeSecretsError('Supplied application credentials do not meet deployment requirements')
        if value and (any(char in value for char in ('\0','\r','\n'))
                      or len((prefixed+'='+shlex.quote(value)).encode())>4096):
            raise RuntimeSecretsError('Application credentials must fit a single literal assignment')


def ensure(path,environment):
    """Add missing application keys through a checked, locked file descriptor.

    The caller holds deploy.lock. This additional file lock serializes direct
    ensure callers; no shell redirection or chmod reopens a checked pathname.
    """
    if os.name!='posix':
        raise RuntimeSecretsError('Credential initialization requires POSIX file ownership')
    path=Path(path)
    # Reject missing/invalid operator credentials before creating any file.
    validate_deployment(load(path,allow_missing=True),environment)
    with private_directory(path) as directory:
        return ensure_in_directory(path,directory,environment)


def ensure_in_directory(path,directory,environment):
    import fcntl
    flags=os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK
    try:
        fd=os.open(path.name,flags,dir_fd=directory)
    except FileNotFoundError:
        fd=os.open(path.name,flags|os.O_CREAT|os.O_EXCL,0o600,dir_fd=directory)
    with os.fdopen(fd,'r+b',buffering=0) as source:
        fcntl.flock(source.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        raw,values=read_private(source)
        validate_deployment(values,environment)
        effective=dict(environment)
        effective.update(values)
        additions={key:(effective.get(key.removeprefix('WEBCOMPILER_')) or effective.get(key)
                        or secrets.token_urlsafe(size)) for key,size in
                   (('WEBCOMPILER_SECRET_KEY',48),('WEBCOMPILER_ADMIN_PASSWORD',32)) if key not in values}
        data=(b'\n' if raw and not raw.endswith(b'\n') else b'')+''.join(
            key+'='+shlex.quote(value)+'\n' for key,value in additions.items()).encode()
        if len(raw)+len(data)>MAX_BYTES:
            raise RuntimeSecretsError('Runtime secrets file has no space for missing credentials')
        opened=os.fstat(source.fileno())
        def verify_path():
            current=os.stat(path.name,dir_fd=directory,follow_symlinks=False)
            if ((opened.st_dev,opened.st_ino)!=(current.st_dev,current.st_ino)
                    or not stat.S_ISREG(current.st_mode) or current.st_mode&0o077
                    or current.st_uid!=os.getuid()):
                raise RuntimeSecretsError('Runtime secrets changed during initialization')
        verify_path()
        if not additions:
            return values
        # A subsequent pathname replacement cannot redirect this descriptor.
        source.seek(0,os.SEEK_END)
        remaining=memoryview(data)
        while remaining:
            written=source.write(remaining)
            if not written:
                raise RuntimeSecretsError('Unable to persist runtime credentials')
            remaining=remaining[written:]
        os.fsync(source.fileno())
        verify_path()
        values.update(additions)
        return values


def exports(values):
    if any(key not in ALLOWED_KEYS or not isinstance(value,str) or '\0' in value
           for key,value in values.items()):
        raise RuntimeSecretsError('Invalid runtime credential mapping')
    return '\n'.join('export '+key+'='+shlex.quote(value) for key,value in sorted(values.items()))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('validate','keys','ensure','exports'))
    parser.add_argument('--file',required=True,type=Path)
    parser.add_argument('--allow-missing',action='store_true')
    parser.add_argument('--deployment',action='store_true')
    parser.add_argument('--emit-exports',action='store_true')
    args=parser.parse_args()
    try:
        values=(ensure(args.file,os.environ) if args.operation=='ensure' else
                load(args.file,allow_missing=args.allow_missing and args.operation in ('validate','keys')))
        if args.deployment:
            validate_deployment(values,os.environ)
        if args.operation=='exports' or (args.operation=='ensure' and args.emit_exports):
            print(exports(values))
        elif args.operation=='keys':
            print('\n'.join(sorted(values)))
    except (RuntimeSecretsError,OSError,UnicodeError):
        print('Runtime secrets rejected; use a private literal credential/mail file and configure deployment scope before preflight',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
