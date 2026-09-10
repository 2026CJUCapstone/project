"""A zombie group leader is not proof that its other native threads stopped."""
import os
from pathlib import Path
import select
import socket
import subprocess
import sys
import time
from uuid import uuid4

import pytest

from app.services.process_observation import local_process_state
from app.services.worker_process import ProcessIdentity, configured_scope, process_start_token


pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='Actual Linux pthread/proc semantics required')


@pytest.mark.parametrize('threaded',[False,True])
def test_group_leader_exit_retains_liveness_until_last_native_thread_exits(threaded):
    source='''import ctypes, os, threading
gate=threading.Event()
def worker():
    print('ready',flush=True)
    gate.wait()
    os.read(0,1)
threading.Thread(target=worker).start()
os.read(0,1)
gate.set()
libc=ctypes.CDLL(None)
libc.pthread_exit.argtypes=[ctypes.c_void_p]
libc.pthread_exit.restype=None
libc.pthread_exit(None)
''' if threaded else "import os; print('ready',flush=True); os.read(0,1); os._exit(0)"
    child=subprocess.Popen([sys.executable,'-c',source],stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    try:
        assert select.select([child.stdout],[],[],5)[0]
        assert child.stdout.readline().strip()==b'ready'
        identity=ProcessIdentity(uuid4().hex,child.pid,process_start_token(child.pid),
            socket.gethostname(),configured_scope())
        assert local_process_state(identity)=='alive'
        child.stdin.write(b'x')
        child.stdin.flush()
        deadline=time.monotonic()+5
        while True:
            fields=Path(f'/proc/{child.pid}/stat').read_text().rsplit(')',1)[1].split()
            if fields[0]=='Z':
                break
            assert time.monotonic()<deadline
            time.sleep(.01)
        if threaded:
            assert int(fields[17])>=2 and child.poll() is None
            with pytest.raises(OSError,match='Thread group termination is unproven'):
                process_start_token(child.pid)
            assert local_process_state(identity)=='unknown'
            child.communicate(b'y',timeout=5)
        else:
            assert fields[17]=='1'
            assert local_process_state(identity)=='absent'
            child.communicate(timeout=5)
        assert child.returncode==0
        assert local_process_state(identity)=='absent'
    finally:
        if child.poll() is None:
            child.kill()  # Only the fixture-created child, never an observed arbitrary PID.
            child.wait(timeout=5)
        for stream in (child.stdin,child.stdout):
            if stream is not None:
                stream.close()
