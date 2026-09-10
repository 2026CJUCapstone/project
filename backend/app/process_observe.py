"""Private read-only kernel observation in the target process's own namespace."""
import argparse
import json

from app.core.database import SessionLocal
from app.services.process_observation import ProcessObserver
from app.services.runtime_identity import RuntimeIdentity


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=('api','worker'), required=True)
    parser.add_argument('--epoch', required=True)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--pool', required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--sandbox-pool', required=True)
    args = parser.parse_args(argv)
    try:
        runtime = RuntimeIdentity(args.runtime,args.pool,args.release,args.sandbox_pool)
        if runtime != RuntimeIdentity.configured():
            raise ValueError('Wrong configured runtime')
        result = ProcessObserver(SessionLocal,runtime).observe(args.role,args.epoch)
        print(json.dumps(result,sort_keys=True))
        if result['state'] == 'unknown':
            parser.exit(1)
    except Exception:
        parser.exit(1,'Process observation unavailable; no retirement authorization\n')


if __name__ == '__main__':
    main()
