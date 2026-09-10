"""Private DB/kernel evidence for an exact fenced runtime. Never stops work."""
import argparse
import json

from app.core.database import SessionLocal
from app.services.runtime_evidence import RuntimeEvidence
from app.services.runtime_identity import RuntimeIdentity


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',required=True)
    parser.add_argument('--pool',required=True)
    parser.add_argument('--release',required=True)
    parser.add_argument('--sandbox-pool',required=True)
    parser.add_argument('--local-role',choices=('api','worker'))
    args = parser.parse_args(argv)
    try:
        runtime = RuntimeIdentity(args.runtime,args.pool,args.release,args.sandbox_pool)
        if runtime!=RuntimeIdentity.configured():
            raise ValueError('Wrong configured runtime')
        evidence = RuntimeEvidence(SessionLocal,runtime)
        result = evidence.local(args.local_role) if args.local_role else evidence.snapshot()
        print(json.dumps(result,sort_keys=True))
        if args.local_role and (not result['processes'] or any(
                process['state']=='unknown' for process in result['processes'])):
            parser.exit(1)
    except Exception:
        parser.exit(1,'Runtime evidence unavailable; no retirement authorization\n')


if __name__=='__main__':
    main()
