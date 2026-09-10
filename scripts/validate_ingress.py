"""Read-only deployment gate; never guess the TLS/host-edge peer addresses."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.services.trusted_ingress import trusted_networks


def validate(environ):
    for key in ('WEBCOMPILER_EDGE_TRUSTED_INGRESS_CIDRS', 'WEBCOMPILER_PROXY_TRUSTED_INGRESS_CIDRS'):
        if not trusted_networks(environ.get(key, '')):
            raise ValueError(f'{key} must explicitly identify the verified immediate proxy peers')


if __name__ == '__main__':
    try:
        validate(os.environ)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2) from None
