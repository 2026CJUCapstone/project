"""Real Docker bridge lifecycle; isolated audit host only, stdlib runner."""
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
spec = importlib.util.spec_from_file_location('live_api_network', ROOT/'scripts/ensure_api_network.py')
network = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = network
spec.loader.exec_module(network)


@unittest.skipUnless(os.getenv('RUN_SHARED_REDIS_INTEGRATION')=='1' and os.name=='posix' and shutil.which('docker'),
                     'Explicit isolated audit host with Docker CLI required')
class ApiNetworkLifecycle(unittest.TestCase):
    def test_color_isolation_repeat_reuse_and_foreign_owner_or_role_refusal(self):
        audit = Path(os.environ['AUDIT_ROOT']).resolve()
        self.assertEqual(audit,ROOT)
        self.assertTrue(audit.name.startswith('webcompiler-audit-'))
        token = uuid4().hex
        configs = [network.Config(str(audit),'audit-network-'+token+'-'+color) for color in ('blue','green')]
        containers = []
        try:
            cidrs = [network.ensure(config) for config in configs]
            self.assertNotEqual(cidrs[0],cidrs[1])
            ids = [json.loads(network.docker(['network','inspect',c.name]))[0]['Id'] for c in configs]
            for config,cidr,network_id in zip(configs,cidrs,ids):
                self.assertEqual(network.ensure(config),cidr)
                self.assertEqual(json.loads(network.docker(['network','inspect',config.name]))[0]['Id'],network_id)
                with self.assertRaises(network.NetworkError):
                    network.ensure(replace(config,root=str(audit/'foreign-owner')))
            for role in ('backend','worker'):
                config = configs[0]
                name = config.project+'-'+role
                container_id = network.docker(['run','-d','--pull','never','--name',name,
                    '--label','io.webcompiler.audit='+token,
                    '--label','com.docker.compose.project='+config.project,
                    '--label','com.docker.compose.service='+role,
                    '--network',config.name,'--memory','16m','--memory-swap','16m',
                    '--cpus','0.05','--pids-limit','16','--read-only','--cap-drop','ALL',
                    '--security-opt','no-new-privileges:true','--entrypoint','sleep','redis:7-alpine@sha256:ff02b58f971e7d7d156a1267e283fcbbeee91773b6aa36c49dac28ecfe28eadf','60']).strip()
                containers.append(container_id)
                if role=='backend':
                    self.assertEqual(network.ensure(config),cidrs[0])
                else:
                    with self.assertRaises(network.NetworkError):
                        network.ensure(config)
                self.assertEqual(json.loads(network.docker(['network','inspect',config.name]))[0]['Id'],ids[0])
        finally:
            for container_id in reversed(containers):
                details = json.loads(network.docker(['container','inspect',container_id]))[0]
                self.assertEqual(details['Config']['Labels']['io.webcompiler.audit'],token)
                network.docker(['rm','-f',container_id])
            for config in configs:
                names = network.docker(['network','ls','--format','{{.Name}}']).splitlines()
                if config.name in names:
                    details = json.loads(network.docker(['network','inspect',config.name]))[0]
                    self.assertTrue(all(details['Labels'].get(k)==v for k,v in config.labels.items()))
                    self.assertFalse(details['Containers'])
                    network.docker(['network','rm',details['Id']])


if __name__=='__main__':
    unittest.main()
