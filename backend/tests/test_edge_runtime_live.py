"""Actual bounded edge HUP/rollback/crash test on the isolated Linux audit host.

Uses fresh loopback-only HTTP fixtures and high ephemeral edge ports. Application
readiness callbacks here are fixtures, not a full production deployment test.
"""
from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from uuid import uuid4


ROOT=Path(__file__).resolve().parents[2]
for name in ('edge_transaction','edge_runtime','runtime_inventory','runtime_binding','sandbox_inventory','runtime_retirement','edge_deploy'):
    if name in sys.modules:
        continue  # Pytest may have loaded shared EdgeError/module identities.
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
edge=sys.modules['edge_transaction']
runtime=sys.modules['edge_runtime']
adapter=sys.modules['edge_deploy']


def request(port,path='/health',*,body=None):
    conn=HTTPConnection('127.0.0.1',port,timeout=20)
    try:
        conn.request('POST' if body else 'GET',path,body=body,headers={'Content-Type':'application/json'})
        response=conn.getresponse()
        return response.status,response.read()
    finally:
        conn.close()


def websocket(port):
    client=socket.create_connection(('127.0.0.1',port),timeout=10)
    client.settimeout(10)
    client.sendall(b'GET /ws/terminal HTTP/1.1\r\nHost: fixture\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n')
    stream=client.makefile('rb')
    if b'101' not in stream.readline():
        raise AssertionError('Expected actual WebSocket upgrade')
    while stream.readline()!=b'\r\n':
        pass
    return client,stream


def frame(stream):
    header=stream.read(2)
    if len(header)!=2 or header[0]!=0x81 or header[1]>=126:
        raise AssertionError('Expected a complete short text frame')
    return stream.read(header[1]).decode()


@unittest.skipUnless(os.getenv('RUN_EDGE_INTEGRATION')=='1' and os.name=='posix' and shutil.which('docker'),
                     'Explicit isolated Linux host with Docker CLI required')
class EdgeRuntimeLifecycle(unittest.TestCase):
    def test_startup_refuses_regular_or_symlink_socket_without_deleting_either(self):
        audit=Path(os.environ['AUDIT_ROOT']).resolve()
        self.assertEqual(audit,ROOT)
        self.assertTrue(audit.name.startswith('webcompiler-audit-'))
        self.assertNotEqual(os.getuid(),0)
        token=uuid4().hex
        folder=Path(tempfile.mkdtemp(prefix='edge-guard-'+token+'-',dir=audit))
        try:
            for kind in ('regular','symlink'):
                with self.subTest(kind=kind):
                    status=folder/kind
                    status.mkdir(mode=0o700)
                    sentinel=status/'sentinel'
                    sentinel.write_text('preserve this fixture')
                    target=status/'control.sock'
                    if kind=='regular':
                        target.write_text('not a socket')
                    else:
                        target.symlink_to('sentinel')
                    result=subprocess.run(['docker','run','--rm','--pull','never',
                        '--network','none','--user',f'{os.getuid()}:{os.getgid()}',
                        '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true',
                        '--memory','32m','--memory-swap','32m','--cpus','0.05','--pids-limit','16',
                        '--label','webcompiler.audit='+token,'--log-driver','none',
                        '--mount','type=bind,source='+str(status)+',target=/status',
                        '--entrypoint','/bin/sh','nginx:1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6','-c',runtime.EDGE_START],
                        capture_output=True,text=True,timeout=15)
                    self.assertEqual(result.returncode,2,result.stdout+result.stderr)
                    self.assertEqual(sentinel.read_text(),'preserve this fixture')
                    if kind=='symlink':
                        self.assertTrue(target.is_symlink())
                    else:
                        self.assertEqual(target.read_text(),'not a socket')
        finally:
            self.assertEqual(folder.parent,audit)
            self.assertTrue(folder.name.startswith('edge-guard-'+token+'-'))
            shutil.rmtree(folder)

    def test_real_combined_edge_switch_rollback_crash_and_held_http_websocket(self):
        audit=Path(os.environ['AUDIT_ROOT']).resolve()
        self.assertEqual(audit,ROOT)
        self.assertTrue(audit.name.startswith('webcompiler-audit-'))
        self.assertNotEqual(os.getuid(),0)
        token=uuid4().hex
        servers,threads,sockets=[],[],[]
        runtime_ids={'blue':uuid4().hex,'green':uuid4().hex}
        posts=[]
        post_started,post_finish,ws_finish=threading.Event(),threading.Event(),threading.Event()
        def handler(color,role):
            class Handler(BaseHTTPRequestHandler):
                protocol_version='HTTP/1.1'
                def log_message(self,*args):
                    pass
                def do_GET(self):
                    if self.headers.get('Upgrade','').lower()=='websocket':
                        key=self.headers['Sec-WebSocket-Key']
                        accept=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                        self.send_response(101)
                        self.send_header('Upgrade','websocket')
                        self.send_header('Connection','Upgrade')
                        self.send_header('Sec-WebSocket-Accept',accept)
                        self.end_headers()
                        payload=color.encode()
                        self.wfile.write(bytes([0x81,len(payload)])+payload)
                        self.wfile.flush()
                        if ws_finish.wait(30):
                            self.wfile.write(b'\x81\x04done')
                            self.wfile.flush()
                        self.close_connection=True
                        return
                    self.reply()
                def do_POST(self):
                    size=int(self.headers.get('Content-Length','0'))
                    if size>1024:
                        self.send_error(413)
                        return
                    posts.append((color,self.rfile.read(size)))
                    post_started.set()
                    post_finish.wait(30)
                    self.reply()
                def reply(self):
                    sha=('a' if color=='blue' else 'b')*40
                    value={'color':color,'role':role,'path':self.path,'status':'ok','deploymentSha':sha,
                           'runtimeInstanceId':runtime_ids[color]}
                    if self.path=='/ready':
                        value={'status':'ready'}
                    if role=='frontend' and self.path=='/webcompiler/.well-known/webcompiler-release.json':
                        value={'deployment_sha':sha}
                    body=json.dumps(value).encode()
                    self.send_response(200)
                    self.send_header('Content-Length',str(len(body)))
                    self.send_header('Content-Type','application/json')
                    self.end_headers()
                    self.wfile.write(body)
            return Handler
        temp=Path(tempfile.mkdtemp(prefix='edge-'+token+'-',dir=audit))
        store=None
        proxy=None
        pool=ThreadPoolExecutor(max_workers=1)
        try:
            ports=[]
            for color in ('blue','green'):
                for role in ('api','frontend'):
                    server=ThreadingHTTPServer(('127.0.0.1',0),handler(color,role))
                    server.daemon_threads=True
                    servers.append(server)
                    ports.append(server.server_port)
                    thread=threading.Thread(target=server.serve_forever,daemon=True)
                    threads.append(thread)
                    thread.start()
            # Reserve two distinct high ports only for this fixture. Runtime
            # rechecks conflicts and refuses; it never kills another listener.
            reserved=[]
            for _ in range(2):
                sock=socket.socket()
                sock.bind(('127.0.0.1',0))
                reserved.append(sock)
            layout=edge.Layout(*(sock.getsockname()[1] for sock in reserved))
            for sock in reserved:
                sock.close()
            (temp/'.deploy').mkdir(mode=0o700)
            config=adapter.Config(temp,layout,(ports[0],ports[1]),(ports[2],ports[3]),
                                  edge_name='audit-edge-'+token,project_prefix='audit-'+token,
                                  legacy_names=('audit-legacy-'+token,))
            deployed=adapter.Deployment(config)
            # This fixture owns HTTP servers, not a real application Compose
            # color. Container ownership is not covered by this edge fixture.
            deployed.capture_inventory=lambda _:True
            deployed.verify_inventory=lambda _:True
            store=deployed.store
            store.initialize()
            # Require the exact production pin, never silently substitute a
            # moving family tag that happens to report the same binary version.
            runtime.docker(['image','inspect','nginx:1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6'])
            proxy=deployed.runtime
            blue=edge.Release('blue','a'*40,ports[0],ports[1],uuid4().hex,runtime_ids['blue'])
            green=edge.Release('green','b'*40,ports[2],ports[3],uuid4().hex,runtime_ids['green'])
            def postflight(release):
                def check():
                    if release is None:
                        return all(request(port)[0]==503 for port in (layout.api_port,layout.frontend_port))
                    for port in (layout.api_port,layout.frontend_port):
                        status,body=request(port)
                        if status!=200 or json.loads(body)['color']!=release.color:
                            return False
                    body=json.loads(request(layout.frontend_port,'/')[1])
                    return (body['color'],body['role'])==(release.color,'frontend')
                return runtime.wait_postflight(check)
            tx=edge.Transaction(store,proxy.activate,postflight,observe=proxy.observe)
            self.assertEqual(deployed.prepare(),'')
            self.assertIsNone(tx.recover())
            self.assertEqual(request(layout.api_port)[0],503)
            # This test has HTTP role fixtures, not actual API controllers.
            # The production two-peer gate is exercised in ready_proxy_live;
            # here all adapter HTTP probes, state, and Nginx actions are real.
            deployed.gate=lambda _:True
            candidate=deployed.candidate('blue','a'*40)
            runtime_ids['blue']=candidate.runtime_id
            self.assertEqual(deployed.switch('blue','a'*40),'blue')
            blue=store.committed()
            self.assertEqual(deployed.projection.read_text(),'blue\n')
            self.assertEqual(proxy.observe(),edge.acknowledgment(layout,blue))
            for port in (layout.api_port,layout.frontend_port):
                self.assertEqual(request(port,'/generation')[0],404)
                self.assertEqual(request(port,'/_edge_generation')[0],404)
                self.assertEqual(request(port,'/configuration')[0],404)
            pending=pool.submit(request,layout.frontend_port,'/api/held',body=b'{"requestId":"one"}')
            self.assertTrue(post_started.wait(5))
            client,stream=websocket(layout.frontend_port)
            sockets.append((client,stream))
            self.assertEqual(frame(stream),'blue')
            def fail_after_green_ws(release):
                self.assertTrue(postflight(release))
                candidate,reader=websocket(layout.frontend_port)
                sockets.append((candidate,reader))
                self.assertEqual(frame(reader),'green')
                return False
            with self.assertRaisesRegex(edge.EdgeError,'committed route restored'):
                tx.switch(green,preflight=lambda _:True,postflight=fail_after_green_ws)
            self.assertEqual(store.committed(),blue)
            self.assertTrue(postflight(blue))
            # Both old-blue and provisional-green connections survive reload
            # and rollback. Neither upstream is stopped as a shortcut to drain.
            post_finish.set()
            self.assertEqual(json.loads(pending.result(timeout=10)[1])['color'],'blue')
            self.assertEqual(posts,[('blue',b'{"requestId":"one"}')])
            ws_finish.set()
            for _,reader in sockets:
                self.assertEqual(frame(reader),'done')
            tx.switch(green,preflight=lambda _:True,postflight=postflight)
            # An actual killed subprocess leaves the candidate disk config
            # before HUP. Restart can expose it; recover must restore COMMIT.
            crash=replace_generation(blue)
            program='''import json,os,sys
sys.path.insert(0,sys.argv[1])
from edge_transaction import Store,Layout,Release
store=Store(sys.argv[2],Layout(**json.loads(sys.argv[3])))
store.initialize()
with store.locked():
    target=Release(**json.loads(sys.argv[4]))
    store.intent(target,'switch')
    store.install(target)
    os._exit(23)
'''
            child=subprocess.run([sys.executable,'-c',program,str(ROOT/'scripts'),str(store.path),
                                  json.dumps(layout.__dict__),json.dumps(crash.__dict__)],capture_output=True,timeout=10)
            self.assertEqual(child.returncode,23,child.stderr)
            self.assertTrue((store.path/'state/pending.json').exists())
            runtime.docker(['restart','--time','5',proxy.name])
            # No extra HUP: verify the restart itself adopted the disk state.
            self.assertTrue(proxy.wait_ack(crash))
            self.assertEqual(json.loads(request(layout.api_port)[1])['color'],'blue')
            self.assertEqual(edge.Transaction(store,proxy.activate,postflight,observe=proxy.observe).recover(),green)
            self.assertTrue(postflight(green))
            self.assertFalse((store.path/'state/pending.json').exists())
            self.assertEqual(deployed.prepare(),'green')
            self.assertEqual(deployed.projection.read_text(),'green\n')
            # Actual process death after durable commit but before intent
            # cleanup must retain the new route, not restore the prior color.
            committed_program=program.replace('    os._exit(23)', '''    from edge_runtime import Runtime
    proxy=Runtime(store,name=sys.argv[5])
    assert proxy.activate(target)
    store.commit(target)
    os._exit(24)''')
            child=subprocess.run([sys.executable,'-c',committed_program,str(ROOT/'scripts'),str(store.path),
                                  json.dumps(layout.__dict__),json.dumps(crash.__dict__),proxy.name],
                                 capture_output=True,timeout=20)
            self.assertEqual(child.returncode,24,child.stderr)
            self.assertEqual(store.committed(),crash)
            self.assertTrue((store.path/'state/pending.json').exists())
            self.assertEqual(deployed.prepare(),'blue')
            self.assertEqual(store.committed(),crash)
            self.assertEqual(deployed.projection.read_text(),'blue\n')
            self.assertTrue(postflight(crash))
            self.assertFalse((store.path/'state/pending.json').exists())
            # The unclean master exit leaves the UDS pathname behind. Prove
            # automatic restart can recover it without deleting foreign paths.
            # docker kill is an operator stop and suppresses unless-stopped
            # restart. Kill the verified owned master via a pinned pidfd to
            # simulate process failure without a PID-reuse or manual-stop race.
            container=proxy.inspect()
            pinned=json.loads(runtime.docker(['image','inspect',proxy.image]))[0]['Id']
            proxy.validate(container,pinned)
            master=container['State']['Pid']
            self.assertGreater(master,1)
            descriptor=os.pidfd_open(master)
            try:
                self.assertEqual(Path(f'/proc/{master}').stat().st_uid,os.getuid())
                self.assertTrue(Path(f'/proc/{master}/cmdline').read_bytes().startswith(b'nginx: master process'))
                self.assertEqual(proxy.inspect()['State']['Pid'],master)
                signal.pidfd_send_signal(descriptor,signal.SIGKILL)
            finally:
                os.close(descriptor)
            acknowledged=proxy.wait_ack(crash)
            if not acknowledged:
                state=proxy.inspect()
                logs=subprocess.run(['docker','logs','--tail','12',proxy.name],
                                    capture_output=True,text=True,timeout=10)
                self.fail(f"Crash restart unacknowledged: {state['State']}; "
                          +logs.stdout+logs.stderr)
            self.assertTrue(postflight(crash))
            restarted=proxy.inspect()
            self.assertNotEqual(restarted['State']['Pid'],master)
            self.assertGreater(restarted['RestartCount'],container['RestartCount'])
        finally:
            post_finish.set()
            ws_finish.set()
            for client,stream in sockets:
                stream.close()
                client.close()
            pool.shutdown(wait=True)
            if proxy:
                container=proxy.inspect()
                if container:
                    self.assertTrue(all(container['Config']['Labels'].get(k)==v for k,v in proxy.labels.items()))
                    runtime.docker(['rm','-f',container['Id']])
            for server in servers:
                server.shutdown()
                server.server_close()
            self.assertEqual(temp.parent,audit)
            self.assertTrue(temp.name.startswith('edge-'+token+'-'))
            shutil.rmtree(temp)


def replace_generation(release):
    return edge.Release(release.color,release.sha,release.api_port,release.frontend_port,uuid4().hex,release.runtime_id)


if __name__=='__main__':
    unittest.main()
