"""Host-CLI integration of shared Redis; opt in only on the isolated audit host.

Run directly with stdlib unittest. No Docker/Python dependency install needed.
"""
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
spec = importlib.util.spec_from_file_location('audit_shared_redis', ROOT/'scripts/ensure_shared_redis.py')
shared = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = shared
spec.loader.exec_module(shared)


@unittest.skipUnless(os.getenv('RUN_SHARED_REDIS_INTEGRATION') == '1' and os.name == 'posix' and shutil.which('docker'),
    'Explicit isolated audit host with Docker CLI required')
class SharedRedisLifecycle(unittest.TestCase):
    def test_two_color_clients_repeat_start_restart_and_refuse_reconfiguration(self):
        audit = Path(os.environ['AUDIT_ROOT']).resolve()
        self.assertEqual(audit, ROOT)
        self.assertTrue(audit.name.startswith('webcompiler-audit-'))
        project = os.environ['AUDIT_COMPOSE_PROJECT']
        self.assertTrue(project.startswith('webcompiler-audit-'))
        network = project+'_default'
        info = json.loads(shared.docker(['network','inspect',network]))[0]
        self.assertEqual(info['Labels']['com.docker.compose.project'], project)
        token = uuid4().hex
        name = 'audit-shared-redis-'+token
        config = shared.Config(root=str(audit), name=name, volume=name+'-data', network=network,
                               memory_mb=96,maxmemory_mb=32,cpu_millis=125)
        try:
            shared.ensure(config)
            first = json.loads(shared.docker(['container','inspect',name]))[0]
            # Real clients in separate color-like network namespaces see one
            # counter; neither client publishes a port or receives a socket.
            for color, expected in (('blue','1'),('green','2')):
                result = shared.docker(['run','--rm','--pull','never','--name',name+'-'+color,
                    '--label','io.webcompiler.audit='+token,'--network',network,
                    '--memory','32m','--memory-swap','32m','--cpus','0.05','--pids-limit','32',
                    '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges:true',
                    '--entrypoint','redis-cli',config.image,'-h',name,'--raw','INCR','audit-color-counter'])
                self.assertEqual(result.strip(),expected)
            shared.ensure(config)
            self.assertEqual(json.loads(shared.docker(['container','inspect',name]))[0]['Id'],first['Id'])
            self.assertEqual(shared.docker(['exec',name,'redis-cli','--raw','GET','audit-color-counter']).strip(),'2')
            shared.docker(['stop','--time','5',name])
            shared.ensure(config)
            self.assertEqual(shared.docker(['exec',name,'redis-cli','--raw','GET','audit-color-counter']).strip(),'2')
            self.assertIn('noeviction',shared.docker(['exec',name,'redis-cli','CONFIG','GET','maxmemory-policy']))
            # A changed memory policy or another checkout must not recreate,
            # flush or silently adopt the existing service/volume.
            for changed in (replace(config,memory_mb=128),replace(config,root=str(audit/'other-owner'))):
                with self.assertRaises(shared.SharedRedisError):
                    shared.ensure(changed)
                self.assertEqual(shared.docker(['exec',name,'redis-cli','--raw','GET','audit-color-counter']).strip(),'2')
            final = json.loads(shared.docker(['container','inspect',name]))[0]
            self.assertEqual(final['Id'],first['Id'])
            self.assertFalse(final['HostConfig'].get('PortBindings'))
            self.assertEqual(final['HostConfig']['Memory'],96*1024*1024)
        finally:
            # Names include this run's UUID; validate ownership before cleanup.
            for color in ('blue','green'):
                peers = shared.docker(['container','ls','-aq','--filter','label=io.webcompiler.audit='+token,
                                      '--filter','name=^/'+name+'-'+color+'$']).split()
                for peer in peers:
                    shared.docker(['rm','-f',peer])
            ids = shared.docker(['container','ls','-aq','--filter','name=^/'+name+'$']).split()
            for container_id in ids:
                details = json.loads(shared.docker(['container','inspect',container_id]))[0]
                self.assertTrue(all(details['Config']['Labels'].get(k)==v for k,v in config.labels.items()))
                shared.docker(['rm','-f',container_id])
            volumes = shared.docker(['volume','ls','--filter','name=^'+config.volume+'$', '--format','{{.Name}}']).split()
            if config.volume in volumes:
                details = json.loads(shared.docker(['volume','inspect',config.volume]))[0]
                self.assertTrue(all(details['Labels'].get(k)==v for k,v in config.labels.items()))
                shared.docker(['volume','rm',config.volume])


if __name__ == '__main__':
    unittest.main()
