"""Opt-in real Docker ownership/recovery test; no application containers run.

The fixture only creates stopped containers with actual Compose/local sandbox
ownership labels, own volumes/network/tags, and a separate control volume.
It does NOT prove application startup, runtime limits or managed-LB behavior.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import select
import signal
import subprocess
import tempfile
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BASE_IMAGE = ('nginx:1.30.4-alpine-slim@sha256:'
              '77da26c31397bf6694b4bf93275f5b40b0b120ba1b8f114264b603e592c561d6')


@unittest.skipUnless(os.name == 'posix' and shutil.which('docker')
                     and os.environ.get('RUN_E2E_CLEANUP_INTEGRATION') == '1',
                     'Explicit isolated Linux Docker cleanup validation required')
class E2ECleanupLive(unittest.TestCase):
    def test_setup_child_retains_lock_after_parent_is_killed(self):
        with tempfile.TemporaryDirectory(prefix='audit-e2e-lock-child-') as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            source = root / 'scripts/e2e_stack_test.py'
            shutil.copyfile(ROOT / 'scripts/e2e_stack_test.py', source)
            child_program = 'import os,time; print(os.getpid(), flush=True); time.sleep(30)'
            parent_program = (
                'import importlib.util,sys; from pathlib import Path; '
                's=importlib.util.spec_from_file_location("lockparent",sys.argv[1]); '
                'm=importlib.util.module_from_spec(s); s.loader.exec_module(m);\n'
                'with m.workspace_lock(m.ROOT_DIR):\n'
                ' m.run_command(sys.executable,"-c",sys.argv[2])\n')
            parent = subprocess.Popen(['python3', '-c', parent_program, str(source), child_program],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=root)
            child_handle = None
            try:
                self.assertTrue(select.select([parent.stdout], [], [], 10)[0], 'Child did not report PID')
                child_pid = int(parent.stdout.readline().strip())
                child_handle = os.pidfd_open(child_pid)
                parent.kill()
                parent.wait(timeout=5)
                spec = importlib.util.spec_from_file_location('recover_after_parent_exit', source)
                recovered = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(recovered)
                with self.assertRaisesRegex(RuntimeError, 'Another E2E run owns'):
                    with recovered.workspace_lock(root, recovery=True):
                        self.fail('Recovery stole a live setup child lock')
            finally:
                if parent.poll() is None:
                    parent.kill()
                    parent.wait(timeout=5)
                if child_handle is not None:
                    try:
                        signal.pidfd_send_signal(child_handle, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    finally:
                        os.close(child_handle)
                parent.communicate(timeout=5)

    def test_real_owned_resources_recovery_and_foreign_volume_survival(self):
        with tempfile.TemporaryDirectory(prefix='audit-e2e-cleanup-') as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            source = root / 'scripts/e2e_stack_test.py'
            shutil.copyfile(ROOT / 'scripts/e2e_stack_test.py', source)

            def load():
                spec = importlib.util.spec_from_file_location('live_e2e_' + uuid4().hex, source)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module

            module = load()
            def docker(*args):
                return subprocess.run(['docker', *args], env=module.ENV, cwd=root,
                    capture_output=True, text=True, check=True, timeout=30).stdout.strip()

            # Use the immutable base already present from earlier image tests.
            # Do not pull, build, launch processes, or alter its tag.
            base_id = docker('image', 'inspect', '--format', '{{.Id}}', BASE_IMAGE)
            containers, volumes, networks, tags = [], [], [], []
            try:
                with module.workspace_lock(root):
                    module.record_ownership()
                    namespace = module.E2E_NAMESPACE
                    record = (root / '.e2e-stack-owner.json').read_bytes()
                    self.assertEqual((root / '.e2e-stack-owner.json').stat().st_mode & 0o777, 0o600)
                    work = root / '.sandbox-work' / 'job'
                    work.mkdir(parents=True)
                    (work / 'code.txt').write_text('isolated fixture')
                    data = root / '.data' / namespace
                    data.mkdir(parents=True)
                    (data / 'fixture.txt').write_text('owned data')
                    for tag in module.test_image_tags():
                        docker('image', 'tag', BASE_IMAGE, tag)
                        tags.append(tag)
                    label = 'com.docker.compose.project=' + namespace
                    network = docker('network', 'create', '--label', label, namespace + '_default')
                    networks.append(network)
                    for suffix in ('postgres_data', 'redis_data'):
                        name = namespace + '_' + suffix
                        docker('volume', 'create', '--label', label, name)
                        volumes.append(name)
                    control = 'audit-e2e-control-' + uuid4().hex
                    docker('volume', 'create', '--label', 'com.docker.compose.project=' + control, control)
                    volumes.append(control)
                    for service in ('worker', 'postgres'):
                        cid = docker('container', 'create', '--name', namespace + '-' + service,
                            '--network', network, '--memory', '32m', '--memory-swap', '32m',
                            '--cpus', '0.1', '--pids-limit', '16', '--label', label,
                            '--label', 'com.docker.compose.service=' + service,
                            '--label', 'com.docker.compose.project.working_dir=' + str(root),
                            '--mount', 'type=volume,source=' + volumes[0] + ',target=/fixture',
                            '--entrypoint', '/bin/true', module.BACKEND_IMAGE)
                        containers.append(cid)
                    cid = docker('container', 'create', '--name', namespace + '-sandbox',
                        '--network', 'none', '--memory', '32m', '--memory-swap', '32m',
                        '--cpus', '0.1', '--pids-limit', '16',
                        '--label', 'webcompiler.pool=' + namespace,
                        '--label', 'webcompiler.job=' + '1' * 32,
                        '--label', 'webcompiler.lease=' + '2' * 32,
                        '--mount', 'type=bind,source=' + str(work) + ',target=/work',
                        '--entrypoint', '/bin/true', module.SANDBOX_IMAGE)
                    containers.append(cid)
                    # Every fixture create has returned, and these containers
                    # have never run. This exercises post-settlement cleanup,
                    # not the product DB/worker settlement protocol.
                    module.record_checkpoint('setup-complete')
                    module.record_checkpoint('producers-settled')
                    # A separate process must not clean a still-owned run.
                    busy = subprocess.run(['python3', str(source), '--cleanup'], cwd=root,
                        env=module.ENV, capture_output=True, text=True, timeout=30)
                    self.assertNotEqual(busy.returncode, 0)
                    self.assertIn('Another E2E run owns', busy.stderr)
                    self.assertEqual(len(module.owned_resources()['container']), 2)
                # Simulate process loss: import creates a different nonce first.
                recovered = load()
                self.assertNotEqual(recovered.E2E_NAMESPACE, namespace)
                with recovered.workspace_lock(root, recovery=True):
                    self.assertTrue(recovered.restore_ownership())
                    self.assertEqual(recovered.E2E_NAMESPACE, namespace)
                    self.assertEqual(recovered.test_image_tags(), module.test_image_tags())
                    self.assertEqual(recovered.ENV['COMPOSE_PROJECT_NAME'], namespace)
                    recovered.cleanup_owned_stack()
                    recovered.cleanup_owned_stack()
                self.assertFalse(any(recovered.owned_resources().values()))
                self.assertFalse(any(recovered.image_exists(tag) for tag in tags))
                self.assertFalse(work.parent.exists())
                self.assertFalse(data.exists())
                self.assertEqual((root / '.e2e-stack-owner.json').read_bytes(), record)
                self.assertEqual(docker('volume', 'inspect', '--format', '{{.Name}}', control), control)
                self.assertEqual(docker('image', 'inspect', '--format', '{{.Id}}', BASE_IMAGE), base_id)
                # CLI recovery is independently idempotent and sees old nonce.
                subprocess.run(['python3', str(source), '--cleanup'], cwd=root,
                    env=module.ENV, capture_output=True, text=True, check=True, timeout=30)
            finally:
                # Fallback only for this fixture's IDs/names returned by create.
                # No glob, global prune, external volume or base image deletion.
                failures = []
                for kind, values in (('container', containers), ('volume', volumes),
                                     ('network', networks), ('image', tags)):
                    for value in values:
                        listing = ('ps', '-aq', '--no-trunc') if kind == 'container' else (
                            kind, 'ls', '-q', *(['--no-trunc'] if kind == 'network' else []))
                        present = (bool(docker('image', 'ls', '-q', '--filter', 'reference=' + value))
                                   if kind == 'image' else value in docker(*listing).splitlines())
                        if present:
                            try:
                                docker(kind, 'rm', *(['-f'] if kind == 'container' else []), value)
                            except subprocess.CalledProcessError:
                                failures.append(kind + ':' + value)
                if failures:
                    raise RuntimeError('Fixture cleanup failed: ' + ', '.join(failures))


if __name__ == '__main__':
    unittest.main()
