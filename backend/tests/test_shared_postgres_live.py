"""Host CLI lifecycle; opt in only in a separate disposable audit source directory."""
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('audit_postgres_live_helper', ROOT/'scripts/ensure_shared_postgres.py')
shared = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = shared
spec.loader.exec_module(shared)


@unittest.skipUnless(os.getenv('RUN_SHARED_POSTGRES_INTEGRATION') == '1'
    and os.name == 'posix' and shutil.which('docker'), 'Explicit isolated audit host with Docker CLI required')
class OwnedPostgresLifecycle(unittest.TestCase):
    def test_color_clients_durable_restart_and_refused_adoption(self):
        audit = Path(os.environ['AUDIT_ROOT']).resolve()
        self.assertEqual(audit, ROOT)
        self.assertTrue(audit.name.startswith('webcompiler-audit-'))
        token = uuid4().hex
        name = 'audit-owned-pg-' + token
        config = shared.Config(root=str(audit), password='audit-only-' + token,
            name=name, volume=name+'-data', network=name+'-network',
            memory_mb=256, cpu_millis=250)
        def sql(statement):
            return shared.docker(['exec', '--env', 'PGPASSWORD', name, 'psql', '-X', '-w',
                '-h', '127.0.0.1', '-U', config.user, '-d', config.database,
                '-v', 'ON_ERROR_STOP=1', '-tAc', statement], env={'PGPASSWORD': config.password}).strip()
        try:
            container_id = shared.ensure(config)
            first = shared.record(shared.docker, ['container', 'inspect', name])
            self.assertEqual(container_id, first['Id'])
            self.assertFalse(first['HostConfig'].get('PortBindings'))
            self.assertEqual(first['HostConfig']['Memory'], 256*1024*1024)
            self.assertEqual(shared.ensure(config, check_tables=True), 0)
            sql('create table audit_counter(id integer primary key, n integer not null); insert into audit_counter values(1,0)')
            # Two clients in distinct namespaces use the same authenticated DB.
            for color, expected in (('blue', '1'), ('green', '2')):
                result = shared.docker(['run', '--rm', '--pull', 'never', '--name', name+'-'+color,
                    '--label', 'io.webcompiler.audit='+token, '--network', config.network,
                    '--memory', '64m', '--memory-swap', '64m', '--cpus', '0.05', '--pids-limit', '32',
                    '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
                    '--env', 'PGPASSWORD', '--entrypoint', 'psql', first['Image'],
                    '-X', '-w', '-h', name, '-U', config.user, '-d', config.database,
                    '-v', 'ON_ERROR_STOP=1', '-tAc', 'update audit_counter set n=n+1 where id=1 returning n'],
                    env={'PGPASSWORD': config.password})
                self.assertEqual(result.strip().splitlines()[0], expected)
            self.assertEqual(shared.ensure(config), container_id)
            shared.docker(['stop', '--time', '10', container_id])
            self.assertEqual(shared.ensure(config), container_id)
            self.assertEqual(sql('select n from audit_counter where id=1'), '2')
            sql('create table problems(id integer primary key)')
            self.assertEqual(shared.ensure(config, check_tables=True), 1)
            for changed in (replace(config, password='different-audit-password-123456789'),
                            replace(config, memory_mb=384), replace(config, root=str(audit/'another-owner'))):
                with self.assertRaises(shared.SharedPostgresError):
                    shared.ensure(changed)
                self.assertEqual(sql('select n from audit_counter where id=1'), '2')
            self.assertEqual(shared.record(shared.docker, ['container', 'inspect', name])['Id'], container_id)
        finally:
            # Only exact UUID-named and ownership-verified test resources are removed.
            for color in ('blue', 'green'):
                ids = shared.docker(['container', 'ls', '-aq', '--filter', 'label=io.webcompiler.audit='+token,
                    '--filter', 'name=^/'+name+'-'+color+'$']).split()
                for client_id in ids:
                    shared.docker(['rm', '-f', client_id])
            ids = shared.docker(['container', 'ls', '-aq', '--filter', 'name=^/'+name+'$']).split()
            for owned_id in ids:
                info = shared.record(shared.docker, ['container', 'inspect', owned_id])
                self.assertTrue(shared.labels_match(info['Config']['Labels'], config.labels))
                self.assertEqual(info['Name'], '/'+name)
                shared.docker(['rm', '-f', owned_id])
            volumes = shared.docker(['volume', 'ls', '--format', '{{.Name}}']).splitlines()
            if config.volume in volumes:
                shared.validate_volume(shared.record(shared.docker, ['volume', 'inspect', config.volume]), config)
                shared.docker(['volume', 'rm', config.volume])
            networks = shared.docker(['network', 'ls', '--format', '{{.Name}}']).splitlines()
            if config.network in networks:
                info = shared.record(shared.docker, ['network', 'inspect', config.network])
                shared.validate_network(info, config)
                self.assertFalse(info.get('Containers'))
                shared.docker(['network', 'rm', config.network])


if __name__ == '__main__':
    unittest.main()
