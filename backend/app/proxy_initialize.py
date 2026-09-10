"""Initialize one dedicated proxy-control volume; never reset an existing pool."""
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from app.services.api_proxy_config import render_managed
from app.services.runtime_identity import validate_runtime_id
from app.services.trusted_ingress import trusted_networks


def initialize(directory: Path, release: str, pool_id: str, *, runtime_id='', uid=10001, gid=10001, trusted_ingress=''):
    validate_runtime_id(runtime_id, allow_empty=True)
    if not re.fullmatch(r'[0-9a-f]{40}',release):
        raise ValueError('Exact release SHA required')
    if not directory.is_absolute() or directory.is_symlink():
        raise ValueError('Dedicated control volume required')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}',pool_id):
        raise ValueError('Explicit proxy pool identity required')
    entries = list(directory.iterdir())
    marker = directory/'owner.json'
    expected = {'deploymentSha':release,'poolId':pool_id,'runtimeInstanceId':runtime_id,'uid':uid,'gid':gid}
    trusted_ingress = ','.join(str(n) for n in trusted_networks(trusted_ingress))
    if trusted_ingress:
        expected['trustedIngress'] = trusted_ingress
    if entries:
        if marker.is_symlink() or json.loads(marker.read_text()) != expected:
            raise ValueError('Existing control volume belongs to another release')
        info = directory.stat()
        if info.st_uid != uid or info.st_gid != gid or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('Existing control volume permissions differ')
        # In-progress state belongs to a running controller, never bootstrap it
        # back to an empty pool on a repeated initializer invocation.
        return
    generation = uuid4().hex
    for name, value in (('nginx.conf',render_managed([],generation,trusted_ingress=trusted_ingress)),
                        ('generation-'+generation,generation),
                        ('owner.json',json.dumps(expected))):
        path = directory/name
        with path.open('x',encoding='utf-8') as output:
            output.write(value)
        os.chmod(path,0o600)
        os.chown(path,uid,gid)
    os.chmod(directory,0o700)
    os.chown(directory,uid,gid)


if __name__ == '__main__':
    initialize(Path('/control'),os.environ['DEPLOYMENT_SHA'],os.environ['PROXY_POOL_ID'],
               runtime_id=validate_runtime_id(os.environ['RUNTIME_INSTANCE_ID']),
               trusted_ingress=os.getenv('PROXY_TRUSTED_INGRESS_CIDRS',''))
