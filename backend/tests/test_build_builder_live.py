"""Opt-in isolated host BuildKit smoke test; not a full compiler/rollout test.

Creates only nonce-scoped Buildx metadata/container/cache/image. The pinned
official BuildKit image may be pulled; it is retained, never globally pruned.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('live_build_builder',ROOT/'scripts/verify_build_builder.py')
builder=importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name]=builder
SPEC.loader.exec_module(builder)
IMAGE='moby/buildkit@sha256:37539dd4d60fc70968d164d3850d903a2c56f6402214a1953fbf9fcb81ada731'


@unittest.skipUnless(os.name=='posix' and os.environ.get('RUN_BOUNDED_BUILDER_INTEGRATION')=='1'
                     and shutil.which('docker'),'Explicit isolated host bounded-builder test required')
class BoundedBuildLive(unittest.TestCase):
    def test_actual_build_uses_bounded_named_builder_and_rejects_drift(self):
        full_build=os.environ.get('RUN_AUDIT_APPLICATION_BUILD')=='1'
        app_e2e=os.environ.get('RUN_AUDIT_APPLICATION_E2E')=='1'
        node_probe=os.environ.get('RUN_AUDIT_NODE_RUNTIME')=='1'
        scan_probe=os.environ.get('RUN_AUDIT_IMAGE_SCAN')=='1'
        self.assertLessEqual(sum((full_build,app_e2e,node_probe,scan_probe)),1,
                             'Isolated probes must not dispatch full application builds')
        memory_mb,cpu_millis,pids=(2048,1000,512) if full_build or app_e2e else (512,250,256)
        self.assertGreater(shutil.disk_usage('/var/lib/docker').free,(14 if full_build or app_e2e else 12)*1024**3,
                           'Insufficient disk headroom for isolated builder smoke test')
        nonce=uuid.uuid4().hex
        name='audit-build-'+nonce[:16]
        node=name+'0'
        container_name='buildx_buildkit_'+node
        volume_name=container_name+'_state'
        tag=name+':probe'
        tags=[tag]
        container_id=None
        preserve_builder=False
        with tempfile.TemporaryDirectory(prefix='audit-bounded-build-') as folder:
            root=Path(folder)
            env={'PATH':os.environ['PATH'],'HOME':str(root),'BUILDX_CONFIG':str(root/'buildx'),
                 'DOCKER_HOST':'unix:///var/run/docker.sock','BUILDKIT_PROGRESS':'plain'}
            def command(args,check=True,timeout=30):
                result=subprocess.run(['docker',*args],env=env,capture_output=True,text=True,timeout=timeout)
                if check and result.returncode:
                    self.fail('Isolated Docker command failed: '+result.stderr[-6000:])
                return result
            def call(args): return command(args).stdout
            self.assertNotEqual(command(['container','inspect',container_name],False).returncode,0)
            self.assertNotEqual(command(['volume','inspect',volume_name],False).returncode,0)
            config_file=root/'buildkitd.toml'
            config_file.write_text('[worker.oci]\nmax-parallelism=1\ngc=true\nreservedSpace="128MB"\nmaxUsedSpace="4GB"\nminFreeSpace="10GB"\n')
            try:
                command(['buildx','create','--name',name,'--node',node,'--driver','docker-container',
                    '--driver-opt','image='+IMAGE,'--driver-opt','memory='+str(memory_mb)+'m',
                    '--driver-opt','memory-swap='+str(memory_mb)+'m','--driver-opt','cpu-period=100000',
                    '--driver-opt','cpu-quota='+str(cpu_millis*100),'--driver-opt','restart-policy=no',
                    '--driver-opt','env.WEBCOMPILER_AUDIT_NONCE='+nonce,
                    '--driver-opt','env.BUILDKIT_STEP_LOG_MAX_SIZE=1048576',
                    '--driver-opt','env.BUILDKIT_STEP_LOG_MAX_SPEED=65536',
                    '--buildkitd-config',str(config_file),'unix:///var/run/docker.sock'],timeout=30)
                command(['buildx','inspect',name,'--bootstrap'],timeout=180)
                observed=json.loads(call(['container','inspect',container_name]))[0]
                container_id=observed['Id']
                self.assertIn('WEBCOMPILER_AUDIT_NONCE='+nonce,observed['Config']['Env'])
                # Buildx exposes no PID driver option. Cap the exact newly
                # created container before submitting any build RUN instruction.
                command(['container','update','--pids-limit',str(pids),container_id])
                config=builder.Config(name,memory_mb,cpu_millis,pids,container_id)
                metadata=[json.loads(line) for line in call(['buildx','ls','--format','{{json .}}']).splitlines() if line.strip()]
                print('Builder metadata shape: '+json.dumps([{
                    'Name':row.get('Name'),'Driver':row.get('Driver'),'Dynamic':row.get('Dynamic'),
                    'Nodes':[{'Name':node.get('Name'),'Status':node.get('Status'),'Endpoint':node.get('Endpoint')}
                             for node in row.get('Nodes',[])]}
                    for row in metadata if row.get('Name')==name]))
                self.assertEqual(builder.verify(config,call),container_id)
                (root/'Dockerfile').write_text('FROM '+IMAGE+'\n'
                    'LABEL io.webcompiler.audit.nonce="'+nonce+'"\n'
                    'RUN echo AUDIT_BUILD_STEP && cat /proc/self/cgroup && '
                    'cat /sys/fs/cgroup/memory.max && cat /sys/fs/cgroup/cpu.max && sleep 8\n')
                # A child cgroup may report "max" even when its parent is
                # capped. Observe the actual host-side RUN PID and ancestry,
                # instead of treating that namespace-local file as proof.
                build=subprocess.Popen(['docker','buildx','build','--builder',name,'--load',
                    '--progress','plain','--tag',tag,str(root)],env=env,
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    step_pid=None
                    deadline=time.monotonic()+90
                    while time.monotonic()<deadline and build.poll() is None:
                        listing=command(['top',container_id,'-eo','pid,args']).stdout
                        for line in listing.splitlines()[1:]:
                            parts=line.split(None,1)
                            if len(parts)==2 and parts[1] in ('sleep 8','/bin/sleep 8'):
                                step_pid=int(parts[0])
                                break
                        if step_pid: break
                        time.sleep(0.25)
                    self.assertIsNotNone(step_pid,'Build RUN process was not observable inside the bounded builder')
                    def cgroup(pid):
                        lines=Path('/proc',str(pid),'cgroup').read_text().splitlines()
                        return next(line.split(':',2)[2] for line in lines if line.startswith('0::'))
                    current=json.loads(call(['container','inspect',container_id]))[0]
                    daemon=cgroup(current['State']['Pid'])
                    parent=builder.container_cgroup('0::'+daemon,container_id)
                    child=cgroup(step_pid)
                    print('Actual build cgroups: '+json.dumps({'container':parent,'daemon':daemon,'step':child}))
                    self.assertTrue(child==parent or child.startswith(parent.rstrip('/')+'/'),
                                    'Build RUN escaped the bounded builder cgroup')
                    cgroup_root=Path('/sys/fs/cgroup')/parent.lstrip('/')
                    self.assertEqual((cgroup_root/'memory.max').read_text().strip(),str(memory_mb*1024**2))
                    self.assertEqual((cgroup_root/'memory.swap.max').read_text().strip(),'0')
                    self.assertEqual((cgroup_root/'cpu.max').read_text().strip(),str(cpu_millis*100)+' 100000')
                    self.assertEqual((cgroup_root/'pids.max').read_text().strip(),str(pids))
                    stdout,stderr=build.communicate(timeout=180)
                    self.assertEqual(build.returncode,0,stderr[-6000:])
                finally:
                    if build.poll() is None:
                        build.terminate()
                        try: build.communicate(timeout=10)
                        except subprocess.TimeoutExpired:
                            build.kill()
                            build.communicate(timeout=10)
                output=stdout+stderr
                self.assertIn('AUDIT_BUILD_STEP',output)
                print('Bounded build cgroup probe:\n'+ '\n'.join(
                    line for line in output.splitlines() if 'AUDIT_BUILD_STEP' in line or
                    '0::' in line or '536870912' in line or '25000 100000' in line))
                print('Host-side RUN ancestry and parent CPU/memory/swap/PID caps verified')
                image=json.loads(call(['image','inspect',tag]))[0]
                self.assertEqual(image['Config']['Labels']['io.webcompiler.audit.nonce'],nonce)
                self.assertEqual(builder.verify(config,call),container_id)
                if scan_probe:
                    # Only identity/installed-inventory plumbing, NOT the
                    # frontend product build. Label a small public base image.
                    scanner=Path(os.environ['TEST_TRIVY']).resolve()
                    cache=Path(os.environ['TEST_TRIVY_CACHE']).resolve()
                    self.assertTrue(scanner.is_file())
                    service_cgroup=Path('/sys/fs/cgroup')/cgroup(os.getpid()).lstrip('/')
                    self.assertEqual((service_cgroup/'memory.max').read_text().strip(),str(768*1024**2))
                    self.assertEqual((service_cgroup/'memory.swap.max').read_text().strip(),'0')
                    self.assertEqual((service_cgroup/'cpu.max').read_text().strip(),'50000 100000')
                    self.assertEqual((service_cgroup/'pids.max').read_text().strip(),'128')
                    scan_tag=name+':image-scan'
                    self.assertNotEqual(command(['image','inspect',scan_tag],False).returncode,0)
                    tags.append(scan_tag)
                    context=root/'scan-context'
                    context.mkdir()
                    (context/'Dockerfile').write_text('FROM nginx:1.30.4-alpine-slim@sha256:77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6\n')
                    iidfile=root/'scan.iid'
                    command(['buildx','build','--builder',name,'--load','--platform','linux/amd64',
                        '--iidfile',str(iidfile),'--tag',scan_tag,
                        '--label','io.webcompiler.audit.nonce='+nonce,
                        '--label','io.webcompiler.source-sha='+'c'*40,
                        '--label','io.webcompiler.image-role=frontend',str(context)],timeout=180)
                    image_id=iidfile.read_text().strip()
                    self.assertRegex(image_id,r'^sha256:[0-9a-f]{64}$')
                    observed=json.loads(call(['image','inspect',image_id]))[0]
                    self.assertEqual(observed['Id'],image_id)
                    scan_args=[sys.executable,str(ROOT/'scripts/scan_image.py'),'--trivy',str(scanner),
                        '--image',image_id,'--source','docker','--scope','application','--commit','c'*40,
                        '--cache-dir',str(cache)]
                    evidence=root/'image-scan-evidence'
                    scanned=subprocess.run(scan_args+['--role','frontend','--output-dir',str(evidence)],
                        env=env,capture_output=True,text=True,timeout=180)
                    self.assertEqual(scanned.returncode,0,scanned.stdout+scanned.stderr)
                    receipt=json.loads((evidence/'manifest.json').read_text())
                    self.assertEqual(receipt['imageId'],image_id)
                    self.assertEqual(receipt['role'],'frontend')
                    self.assertEqual(receipt['uniquePackageIdentities'],21)
                    print('ACTUAL_DOCKER_IID_SCAN '+json.dumps(receipt),flush=True)
                    wrong=root/'wrong-role-evidence'
                    rejected=subprocess.run(scan_args+['--role','backend','--output-dir',str(wrong)],
                        env=env,capture_output=True,text=True,timeout=180)
                    self.assertEqual(rejected.returncode,2,rejected.stdout+rejected.stderr)
                    self.assertIn('requested role',rejected.stdout)
                    self.assertFalse(wrong.exists())
                    self.assertEqual(builder.verify(config,call),container_id)
                if node_probe:
                    spec=importlib.util.spec_from_file_location('audit_node_runtime_probe',ROOT/'backend/tests/node_runtime_probe.py')
                    probe=importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(probe)
                    node_tag=name+':node-runtime'
                    self.assertNotEqual(command(['image','inspect',node_tag],False).returncode,0)
                    tags.append(node_tag)
                    probe.run(self,source_root=ROOT,workdir=root,env=env,builder_name=name,
                        container_id=container_id,nonce=nonce,tag=node_tag,command=command,call=call,
                        verify=lambda:self.assertEqual(builder.verify(config,call),container_id))
                if app_e2e:
                    env.update(WEBCOMPILER_BUILD_BUILDER=name,
                        WEBCOMPILER_BUILD_CONTAINER_ID=container_id,
                        WEBCOMPILER_BUILD_MEMORY_MB=str(memory_mb),
                        WEBCOMPILER_BUILD_CPU_MILLIS=str(cpu_millis),
                        WEBCOMPILER_BUILD_PIDS=str(pids))
                    source=ROOT/'backend/tests/audit_application_e2e.py'
                    spec=importlib.util.spec_from_file_location('audit_real_application_e2e',source)
                    application=importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(application)
                    preserve_builder=True
                    application.run(self,source_root=ROOT,env=env,builder_name=name,
                        container_id=container_id,nonce=nonce,volume_name=volume_name)
                    preserve_builder=False
                if full_build:
                    # Build the actual three product Dockerfiles. No mock
                    # compiler, running production tag, or mutable worktree
                    # from the deployment checkout is used as a substitute.
                    env.update(WEBCOMPILER_BUILD_BUILDER=name,
                        WEBCOMPILER_BUILD_CONTAINER_ID=container_id,
                        WEBCOMPILER_BUILD_MEMORY_MB=str(memory_mb),
                        WEBCOMPILER_BUILD_CPU_MILLIS=str(cpu_millis),
                        WEBCOMPILER_BUILD_PIDS=str(pids))
                    labels={'io.webcompiler.audit.nonce':nonce}
                    app_tags={service:name+':'+service for service in ('backend','frontend','sandbox')}
                    tags.extend(app_tags.values())
                    for app_tag in app_tags.values():
                        self.assertNotEqual(command(['image','inspect',app_tag],False).returncode,0)
                    compose_file=root/'compose.json'
                    compose_file.write_text(json.dumps({'services':{
                        'backend':{'image':app_tags['backend'],'build':{'context':str(ROOT/'backend'),'labels':labels}},
                        'frontend':{'image':app_tags['frontend'],'build':{'context':str(ROOT/'frontend'),
                            'labels':labels,'args':{'FRONTEND_API_UPSTREAM':'api-proxy:8080',
                                'ENVIRONMENT':'production','DEPLOY_SHA':'a'*40,
                                'VITE_APP_BASE_PATH':'/webcompiler/','VITE_API_URL':'/webcompiler'}}}}}))
                    def bounded_build(arguments,label,limit):
                        self.assertEqual(builder.verify(config,call),container_id)
                        print('Starting actual '+label+' build',flush=True)
                        log_path=root/(label+'.log')
                        with log_path.open('w+',errors='replace') as log:
                            process=subprocess.Popen(arguments,env=env,stdout=log,stderr=subprocess.STDOUT,text=True)
                            started=time.monotonic()
                            last_report=started
                            try:
                                while process.poll() is None:
                                    free=shutil.disk_usage('/var/lib/docker').free
                                    self.assertGreater(free,8*1024**3,'Disk safety floor reached during actual build')
                                    self.assertLess(time.monotonic()-started,limit,'Actual build time budget exceeded')
                                    if time.monotonic()-last_report>=30:
                                        print(label+' build running; elapsed='+str(int(time.monotonic()-started))+
                                            's; disk-free-MiB='+str(free//1024**2),flush=True)
                                        last_report=time.monotonic()
                                    time.sleep(1)
                                log.seek(max(0,log.tell()-8000))
                                tail=log.read()
                                self.assertEqual(process.returncode,0,tail)
                                print(label+' build completed in '+str(round(time.monotonic()-started,1))+'s',flush=True)
                            finally:
                                if process.poll() is None:
                                    process.terminate()
                                    try: process.wait(timeout=10)
                                    except subprocess.TimeoutExpired:
                                        process.kill()
                                        process.wait(timeout=10)
                                    # Cancel outstanding build work, only in
                                    # this nonce-owned immutable container.
                                    current=json.loads(call(['container','inspect',container_id]))[0]
                                    self.assertIn('WEBCOMPILER_AUDIT_NONCE='+nonce,current['Config']['Env'])
                                    command(['container','stop','--time','5',container_id],timeout=15)
                        self.assertEqual(builder.verify(config,call),container_id)
                    bounded_build(['docker','compose','-p',name,'--env-file','/dev/null',
                        '-f',str(compose_file),'build','--builder',name],'applications',1200)
                    for service in ('backend','frontend'):
                        observed=json.loads(call(['image','inspect',app_tags[service]]))[0]
                        self.assertEqual(observed['Config']['Labels']['io.webcompiler.audit.nonce'],nonce)
                    # Actual product Dockerfile and pinned compiler source.
                    # This does not claim the whole managed shell rollout ran.
                    pinned_ref=(ROOT/'runtime/bpp-ref.txt').read_text().strip()
                    self.assertRegex(pinned_ref,r'^[0-9a-f]{40}$')
                    bounded_build(['docker','buildx','build','--builder',name,'--load',
                        '--shm-size=2g','--label','io.webcompiler.audit.nonce='+nonce,
                        '--build-arg','BPP_REF='+pinned_ref,'--tag',app_tags['sandbox'],
                        '-f',str(ROOT/'runtime/docker/Dockerfile'),str(ROOT/'runtime')],'sandbox',2400)
                    observed=json.loads(call(['image','inspect',app_tags['sandbox']]))[0]
                    self.assertEqual(observed['Config']['Labels']['io.webcompiler.audit.nonce'],nonce)
                    self.assertEqual(observed['Config']['Labels']['io.bpp.ref'],(ROOT/'runtime/bpp-ref.txt').read_text().strip())
                command(['container','update','--pids-limit',str(pids+1),container_id])
                with self.assertRaises(builder.BuilderError): builder.verify(config,call)
            finally:
                for owned_tag in tags:
                    image_result=command(['image','inspect',owned_tag],False)
                    if image_result.returncode==0:
                        image=json.loads(image_result.stdout)[0]
                        self.assertEqual(image['Config']['Labels'].get('io.webcompiler.audit.nonce'),nonce)
                        command(['image','rm',owned_tag])
                if preserve_builder:
                    print('E2E did not confirm settlement/cleanup. Builder is quarantined; '
                          'do not prune or restart the test. Ownership is in .audit-e2e-builder.json.',flush=True)
                current=command(['container','inspect',container_name],False)
                if current.returncode==0:
                    item=json.loads(current.stdout)[0]
                    self.assertIn('WEBCOMPILER_AUDIT_NONCE='+nonce,item['Config']['Env'])
                    if container_id: self.assertEqual(item['Id'],container_id)
                    self.assertEqual([mount['Name'] for mount in item['Mounts'] if mount['Destination']=='/var/lib/buildkit'],[volume_name])
                    if not preserve_builder:
                        command(['buildx','rm','--force',name],timeout=60)
                        self.assertNotEqual(command(['container','inspect',container_name],False).returncode,0)
                        self.assertNotEqual(command(['volume','inspect',volume_name],False).returncode,0)


if __name__=='__main__': unittest.main()
