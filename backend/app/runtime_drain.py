"""Private, exact-incarnation admission fence. Never stops containers or deletes data."""
import argparse
import json

from app.core.database import SessionLocal
from app.services.runtime_identity import RuntimeIdentity
from app.services.runtime_registry import RuntimeRegistry


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',required=True)
    parser.add_argument('--pool',required=True)
    parser.add_argument('--release',required=True)
    parser.add_argument('--sandbox-pool',required=True)
    parser.add_argument('--begin',action='store_true',help='Persistently stop new claims and API requests for this exact runtime.')
    args=parser.parse_args(argv)
    try:
        expected=RuntimeIdentity(args.runtime,args.pool,args.release,args.sandbox_pool)
        if expected!=RuntimeIdentity.configured():
            raise ValueError('Configured runtime does not match the requested target')
        registry=RuntimeRegistry(SessionLocal)
        if args.begin:
            registry.begin_drain(expected)
        status=registry.status(expected)
        if status is None:
            parser.exit(1,'Runtime is not registered; retirement is unproven\n')
        print(json.dumps(status,sort_keys=True))
    except (ValueError,OSError):
        parser.exit(1,'Runtime operation failed; exact identity or state must be checked\n')
    except Exception:
        # Database exceptions may contain infrastructure credentials/paths.
        parser.exit(1,'Runtime state unavailable; no retirement authorization\n')


if __name__=='__main__':
    main()
