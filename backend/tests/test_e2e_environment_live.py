"""Read-only real Compose resolution with deliberately poisoned caller inputs.

No Docker resources are created: config renders the actual application Compose
file in a disposable source directory, without contacting a remote daemon.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(os.name == 'posix' and shutil.which('docker')
                     and os.environ.get('RUN_E2E_CONFIG_INTEGRATION') == '1',
                     'Explicit Linux Compose config validation required')
class E2EEnvironmentLive(unittest.TestCase):
    def test_actual_compose_ignores_caller_overrides_and_project_dotenv(self):
        with tempfile.TemporaryDirectory(prefix='audit-e2e-config-') as folder:
            root = Path(folder)
            (root / 'scripts').mkdir()
            script = root / 'scripts/e2e_stack_test.py'
            shutil.copyfile(ROOT / 'scripts/e2e_stack_test.py', script)
            shutil.copyfile(ROOT / 'docker-compose.yml', root / 'docker-compose.yml')
            shutil.copyfile(ROOT / 'scripts/e2e-stack.compose.yml', root / 'scripts/e2e-stack.compose.yml')
            # Either implicit override mechanism would alter the actual rendered
            # model. These are inert test strings, never operational credentials.
            (root / '.env').write_text('SANDBOX_MEMORY_MB=999999\n')
            (root / 'compose.override.yaml').write_text(
                'services:\n  poison:\n    image: production-should-not-be-used\n')
            poison = root / 'caller-compose.yml'
            poison.write_text('services:\n  caller_only:\n    image: forbidden\n')
            with patch.dict(os.environ, {
                'COMPOSE_FILE': str(poison), 'COMPOSE_ENV_FILES': str(root / '.env'),
                'COMPOSE_PROFILES': 'production', 'DOCKER_CONTEXT': 'production',
                'DOCKER_HOST': 'ssh://production', 'DOCKER_TLS_VERIFY': '1',
                'WEBCOMPILER_WORKER_UID': '10001', 'WEBCOMPILER_WORKER_GID': '10001',
                'WEBCOMPILER_DOCKER_GID': '999', 'BASH_ENV': '/production/startup',
            }):
                spec = importlib.util.spec_from_file_location('live_e2e_env', script)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            result = subprocess.run(['docker', 'compose', 'config', '--format', 'json'],
                cwd=root, env=module.ENV, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            model = json.loads(result.stdout)
            module.validate_test_budget(model)
            self.assertEqual(model['name'], module.E2E_NAMESPACE)
            self.assertNotIn('poison', model['services'])
            self.assertNotIn('caller_only', model['services'])
            for service in ('initialize', 'backend', 'worker'):
                environment = model['services'][service]['environment']
                self.assertEqual(environment['SANDBOX_MEMORY_MB'], '256')
                self.assertIn('/compiler_e2e', environment['DATABASE_URL'])
                self.assertEqual(environment['SMTP_HOST'], '')
            self.assertEqual(model['services']['postgres']['environment']['POSTGRES_DB'], 'compiler_e2e')
            for service in ('backend', 'frontend'):
                self.assertTrue(all(item['host_ip'] == '127.0.0.1'
                                    for item in model['services'][service]['ports']))
            self.assertNotIn('DOCKER_CONTEXT', module.ENV)
            self.assertNotIn('BASH_ENV', module.ENV)
            # Removing the poison .env is a fixture-only action before testing
            # the actual fresh-workspace lock; no application resources exist.
            (root / '.env').unlink()
            with module.workspace_lock(root):
                with self.assertRaisesRegex(RuntimeError, 'Another E2E run'):
                    with module.workspace_lock(root):
                        self.fail('Concurrent checkout ownership was accepted')
            with module.workspace_lock(root):
                pass


if __name__ == '__main__':
    unittest.main()
