"""Bounded local startup diagnostic, NOT judge-policy or acceptance evidence."""
import argparse
import json
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True)
    parser.add_argument('--runs', type=int, default=12, choices=range(1, 31))
    args = parser.parse_args()
    results = []
    for index in range(args.runs):
        started = time.monotonic()
        try:
            result = subprocess.run([args.node, '-e', 'process.stdout.write("ready")'],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=2, check=False)
            status = 'ok' if result.returncode == 0 and result.stdout == b'ready' else 'error'
        except subprocess.TimeoutExpired:
            status = 'timeout'
        results.append(dict(run=index+1, status=status, wallMs=round((time.monotonic()-started)*1000, 1)))
    print(json.dumps(dict(diagnosticOnly=True, timeoutSeconds=2, runs=results), indent=2))
    return int(any(row['status'] != 'ok' for row in results))


if __name__ == '__main__':
    raise SystemExit(main())
