"""Bounded real base-stack exercise using the product E2E entrypoint.

No image, queue, compiler or database is replaced with a mock. This is still
the base stack, not the final managed load-balancer composition.
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time


def run(test, *, source_root, env, builder_name, container_id, nonce, volume_name):
    source_root = Path(source_root)
    for name in ('.deploy', '.data', '.sandbox-work', '.env', '.e2e-stack-owner.json'):
        test.assertFalse((source_root / name).exists(), 'Actual E2E requires fresh source root: ' + name)
    # Keep recovery identity and full output outside the temporary Buildx
    # metadata directory. These contain no production credential or state.
    ownership = source_root / '.audit-e2e-builder.json'
    with ownership.open('x', encoding='utf-8') as stream:
        json.dump({'builder': builder_name, 'container_id': container_id,
                   'nonce': nonce, 'volume': volume_name}, stream)
    log_path = source_root / '.audit-application-e2e.log'
    print('Actual E2E builder ownership: ' + str(ownership), flush=True)
    print('Actual E2E log: ' + str(log_path), flush=True)
    with log_path.open('x+', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, str(source_root / 'scripts/e2e_stack_test.py')],
            cwd=source_root, env=env, stdout=log, stderr=subprocess.STDOUT,
            text=True, start_new_session=True)
        started = last_report = time.monotonic()
        try:
            while process.poll() is None:
                free = shutil.disk_usage('/var/lib/docker').free
                test.assertGreater(free, 8 * 1024**3, 'Actual E2E disk safety floor reached')
                test.assertLess(time.monotonic() - started, 3600, 'Actual E2E time budget exceeded')
                if time.monotonic() - last_report >= 30:
                    print('Actual application E2E running; elapsed=' + str(int(time.monotonic() - started))
                          + 's; disk-free-MiB=' + str(free // 1024**2), flush=True)
                    last_report = time.monotonic()
                time.sleep(1)
            log.seek(max(0, log.tell() - 16000))
            tail = log.read()
            test.assertEqual(process.returncode, 0, tail)
            print(tail, flush=True)
            print('Actual base-stack application E2E passed in '
                  + str(round(time.monotonic() - started, 1)) + 's', flush=True)
        finally:
            if process.poll() is None:
                # This Popen created the session, never use an inferred PID or
                # affect the server's unrelated processes. Daemon resources
                # remain quarantined unless the E2E protocol confirms cleanup.
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
