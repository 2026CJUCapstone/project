"""Bundle exact-SHA frontend output for the single locked SSH deployment."""
import io
import json
import re
import sys
import tarfile
from pathlib import Path


def package(source, output, sha):
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Invalid release SHA')
    source = Path(source).resolve()
    if not (source / 'index.html').is_file():
        raise ValueError('Missing built frontend')
    marker = 'frontend-dist/.well-known/webcompiler-release.json'
    with tarfile.open(output, 'w:gz') as archive:
        for path in sorted(source.rglob('*')):
            if path.is_symlink():
                raise ValueError('Symlinks are not deployment assets')
            name = 'frontend-dist/' + path.relative_to(source).as_posix()
            if path.is_file() and name != marker:
                archive.add(path, arcname=name, recursive=False)
        body = (json.dumps({'deployment_sha': sha}) + '\n').encode()
        entry = tarfile.TarInfo(marker)
        entry.size, entry.mode = len(body), 0o644
        archive.addfile(entry, io.BytesIO(body))


if __name__ == '__main__':
    package(*sys.argv[1:])
