"""Real graceful Docker stop/client-disconnect contract, isolated host only.

No production containers, network, volumes, images or configuration are changed.
The only forcibly removed containers are newly created, exact-ID guard-checked
fixtures in finally; the product stop operation never sends kill or remove.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from runtime_retirement import request_stop


@unittest.skipUnless(os.getenv('RUN_RUNTIME_STOP_INTEGRATION')=='1',
    'Explicit isolated host Docker stop test required')
class GracefulStopLive(unittest.TestCase):
    def test_timed_out_client_does_not_kill_or_restart_exact_fixture(self):
        audit=Path(os.environ['AUDIT_ROOT']).resolve()
        self.assertTrue(audit.name.startswith('webcompiler-audit-'))
        for signal in ('SIGTERM','SIGQUIT'):
            with self.subTest(signal=signal):
                self.exercise(signal)

    def exercise(self,signal):
        nonce=uuid4().hex
        guard='webcompiler.audit.stop'
        identity=None
        def docker(*args):
            result=subprocess.run(['docker',*args],stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,timeout=15,check=True,text=True)
            self.assertLess(len(result.stdout),65536)
            return result.stdout.strip()
        def inspected():
            data=json.loads(docker('container','inspect',identity))[0]
            self.assertEqual(data['Id'],identity)
            self.assertEqual(data['Config']['Labels'][guard],nonce)
            return data
        def wait_for(predicate):
            deadline=time.monotonic()+12
            while time.monotonic()<deadline:
                if predicate(): return
                time.sleep(.1)
            self.fail('Owned fixture did not reach expected state within 12 seconds')
        def exists(path):
            data=inspected()
            if not data['State']['Running']: return False
            return subprocess.run(['docker','exec',identity,'test','-f',path],
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3).returncode==0
        try:
            # Existing pinned image only; an absent image fails without pulling.
            image=docker('image','inspect','nginx:1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6','--format','{{.Id}}')
            identity=docker('container','create','--name','audit-stop-'+nonce,
                '--label',guard+'='+nonce,'--network','none','--user','10001:10001',
                '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
                '--memory','32m','--memory-swap','32m','--cpus','.1','--pids-limit','16',
                '--log-driver','none','--restart','unless-stopped',
                '--tmpfs','/tmp:size=1m,mode=1777,noexec,nosuid','--entrypoint','/bin/sh',image,
                '-c',"trap 'touch /tmp/signaled; while [ ! -f /tmp/release ]; do sleep .1; done; exit 0' TERM QUIT; "
                'touch /tmp/ready; while :; do sleep .1; done')
            self.assertRegex(identity,r'^[a-f0-9]{64}$')
            docker('container','start',identity)
            wait_for(lambda:exists('/tmp/ready'))
            before=inspected()
            self.assertFalse(request_stop(identity,signal=signal,timeout=1))
            wait_for(lambda:exists('/tmp/signaled'))
            # The daemon received the stop, but the trap deliberately remains
            # live after the observing client has been killed and reaped.
            during=inspected()
            self.assertTrue(during['State']['Running'])
            self.assertEqual(during['State']['StartedAt'],before['State']['StartedAt'])
            docker('exec',identity,'touch','/tmp/release')
            wait_for(lambda:inspected()['State']['Status']=='exited')
            time.sleep(.5)
            after=inspected()
            self.assertFalse(after['State']['Running'])
            self.assertEqual(after['State']['ExitCode'],0)
            self.assertEqual(after['RestartCount'],before['RestartCount'])
            self.assertEqual(after['State']['StartedAt'],before['State']['StartedAt'])
        finally:
            if identity is not None:
                inspected()  # Exact newly created fixture and guard before cleanup.
                docker('container','rm','--force',identity)


if __name__=='__main__':
    unittest.main()
