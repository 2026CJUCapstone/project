"""Resolve real Compose overlays without starting or changing any service."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
POSTGRES_PASSWORD = 'audit_shared_postgres_credential_12345'
API_NETWORK_CIDRS = '172.28.0.0/24'
TRUSTED_INGRESS_CIDRS = '172.30.0.1/32'


@unittest.skipUnless(os.getenv('RUN_SHARED_REDIS_INTEGRATION') == '1' and os.name == 'posix' and shutil.which('docker'),
                     'Explicit host Compose config validation required')
class SharedRuntimeCompose(unittest.TestCase):
    def resolve(self, color, redis_url, prefix='audit-shared', *, production=True, managed=False,
                runtime_instance=None, postgres_password=POSTGRES_PASSWORD,
                database_url=None, migration_database_url=None,
                api_network_cidrs=API_NETWORK_CIDRS,
                trusted_ingress_cidrs=TRUSTED_INGRESS_CIDRS, use_deploy_function=False):
        # No inherited production secrets, Compose profiles, or dotenv files.
        runtime_instance = runtime_instance if runtime_instance is not None else ('1' if color == 'blue' else '2') * 32
        env = {k: os.environ[k] for k in ('PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONFIG') if k in os.environ}
        env.update(PROJECT_ROOT=str(ROOT), WEBCOMPILER_WORKER_UID='10001',
                    WEBCOMPILER_WORKER_GID='10001', WEBCOMPILER_DOCKER_GID='999',
                    WEBCOMPILER_POSTGRES_HOST='audit-shared-postgres',
                    WEBCOMPILER_POSTGRES_PASSWORD=postgres_password,
                    WEBCOMPILER_REDIS_URL=redis_url, WEBCOMPILER_REDIS_KEY_PREFIX=prefix,
                   WEBCOMPILER_SHARED_POSTGRES_NETWORK='audit-private', DEPLOY_SHA='a'*40,
                   # The production overlay must derive the runtime readiness pool
                   # from the actual Compose project, never this caller-controlled
                    # value. Sandbox ownership intentionally remains shared.
                    RUNTIME_POOL_ID='caller-pool-must-not-win',
                    WEBCOMPILER_RUNTIME_INSTANCE_ID=runtime_instance,
                     RUNTIME_INSTANCE_ID='f'*32,
                     SANDBOX_POOL_ID='audit-shared-sandbox')
        if postgres_password is None:
            env.pop('WEBCOMPILER_POSTGRES_PASSWORD')
        if database_url is not None:
            env['WEBCOMPILER_DATABASE_URL'] = database_url
        if migration_database_url is not None:
            env['WEBCOMPILER_MIGRATION_DATABASE_URL'] = migration_database_url
        command = ['docker','compose','--env-file','/dev/null','-p','audit-config-'+color,
                   '-f',str(ROOT/'docker-compose.yml'),'-f',str(ROOT/'docker-compose.deploy.yml')]
        if production:
            command += ['-f',str(ROOT/'docker-compose.shared-runtime.yml')]
        if managed:
            env.update(WEBCOMPILER_API_PROXY_PORT_MAPPING='127.0.0.1:'+('18001' if color=='blue' else '18002')+':8080')
            if api_network_cidrs is not None:
                env['WEBCOMPILER_API_NETWORK_CIDRS'] = api_network_cidrs
            if trusted_ingress_cidrs is not None:
                env['WEBCOMPILER_PROXY_TRUSTED_INGRESS_CIDRS'] = trusted_ingress_cidrs
            command += ['-f',str(ROOT/'docker-compose.lb.yml'),'-f',str(ROOT/'docker-compose.ready-lb.yml')]
        command += ['config','--format','json']
        if use_deploy_function:
            # Execute the actual shell function, not a copied Compose command.
            # config is read-only: no image pull/build or service operation.
            assert managed and production
            source=(ROOT/'scripts/deploy_server.sh').read_text()
            names=('color_backend_port','color_frontend_port','compose_for_color')
            functions=[]
            for name in names:
                match=re.search(r'^'+re.escape(name)+r'\(\) \{.*?^\}',source,re.M|re.S)
                assert match, name+' deploy function is missing'
                functions.append(match.group())
            script='set -eu\n'+'\n'.join(functions)+'\n'
            script+='compose_for_color "$AUDIT_COLOR" config --format json\n'
            env.update(WEBCOMPILER_PROJECT_PREFIX='audit-deploy-e2e',SOURCE_ROOT=str(ROOT),
                COMPOSE_PROJECT_NAME='caller-must-not-win',AUDIT_COLOR=color,
                BLUE_BACKEND_PORT='31001',BLUE_FRONTEND_PORT='31002',
                GREEN_BACKEND_PORT='31003',GREEN_FRONTEND_PORT='31004')
            command=['bash','-c',script]
        return subprocess.run(command, env=env,
                              capture_output=True, text=True, timeout=30)

    def test_actual_deploy_function_binds_custom_project_across_five_overlays(self):
        for color,port in (('blue','31001'),('green','31003')):
            with self.subTest(color=color):
                result=self.resolve(color,'redis://audit-shared-redis:6379/0',managed=True,
                    use_deploy_function=True)
                self.assertEqual(result.returncode,0,result.stderr)
                resolved=json.loads(result.stdout)
                project='audit-deploy-e2e-'+color
                self.assertEqual(resolved['name'],project)
                roles=resolved['services']
                self.assertNotIn('postgres',roles)
                self.assertNotIn('redis',roles)
                for role,service in roles.items():
                    self.assertEqual(service['labels']['io.webcompiler.runtime.pool'],project,role)
                self.assertEqual(roles['backend']['environment']['RUNTIME_POOL_ID'],project)
                self.assertEqual(roles['worker']['environment']['RUNTIME_POOL_ID'],project)
                self.assertEqual(roles['proxy-controller']['environment']['PROXY_POOL_ID'],project)
                self.assertEqual(roles['api-proxy']['ports'][0]['published'],port)
                self.assertIn(project+'-api-plane',{n['name'] for n in resolved['networks'].values()})
                self.assertEqual(resolved['networks']['shared_postgres']['name'],'audit-private')
                self.assertEqual(resolved['volumes']['proxy_control']['name'],
                    project+'-proxy-'+'a'*40+'-'+('1' if color=='blue' else '2')*32)

    def test_both_colors_share_endpoints_without_color_local_stateful_services(self):
        for endpoint in ('redis://audit-shared-redis:6379/0', 'rediss://external.example.invalid:6380/4'):
            for color in ('blue','green'):
                with self.subTest(color=color, endpoint=endpoint):
                    result = self.resolve(color,endpoint)
                    self.assertEqual(result.returncode,0,result.stderr)
                    config = json.loads(result.stdout)
                    services = config['services']
                    expected_pool = 'audit-config-'+color
                    self.assertNotIn('postgres',services)
                    self.assertNotIn('redis',services)
                    for role in ('initialize','backend','worker'):
                        env = services[role]['environment']
                        self.assertEqual(env['REDIS_URL'],endpoint)
                        self.assertEqual(env['REDIS_KEY_PREFIX'],'audit-shared')
                        self.assertEqual(env['DEPLOYMENT_SHA'],'a'*40)
                        self.assertEqual(env['RUNTIME_INSTANCE_ID'],('1' if color == 'blue' else '2') * 32)
                        self.assertNotEqual(env['RUNTIME_INSTANCE_ID'],'f'*32)
                        self.assertIn('shared_postgres',services[role]['networks'])
                    for role in ('backend','worker'):
                        env = services[role]['environment']
                        self.assertEqual(env['RUNTIME_POOL_ID'],expected_pool)
                        self.assertNotEqual(env['RUNTIME_POOL_ID'],'caller-pool-must-not-win')
                        self.assertEqual(env['RUNTIME_INSTANCE_ID'],('1' if color == 'blue' else '2') * 32)
                        self.assertNotEqual(env['RUNTIME_INSTANCE_ID'],'f'*32)
                        self.assertEqual(env['SANDBOX_POOL_ID'],'audit-shared-sandbox')
                    self.assertIn('@audit-shared-postgres:5432/',services['initialize']['environment']['DATABASE_URL'])
                    self.assertEqual(services['pgbouncer']['environment']['DB_HOST'],'audit-shared-postgres')
                    self.assertEqual(services['pgbouncer']['environment']['DB_PASSWORD'],POSTGRES_PASSWORD)
                    for role, host in (('initialize','audit-shared-postgres'),
                                       ('backend','pgbouncer'),('worker','pgbouncer')):
                        parsed = urlsplit(services[role]['environment']['DATABASE_URL'])
                        self.assertEqual(parsed.scheme,'postgresql+psycopg2')
                        self.assertEqual((parsed.username,parsed.password),('compiler',POSTGRES_PASSWORD))
                        self.assertEqual((parsed.hostname,parsed.port,parsed.path),(host,5432,'/compiler'))
                    for role, service in services.items():
                        self.assertTrue(set(service.get('depends_on',{})).issubset(services),role)
                    self.assertTrue(config['networks']['shared_postgres']['external'])
                    self.assertEqual(config['networks']['shared_postgres']['name'],'audit-private')

    def test_production_refuses_missing_shared_settings(self):
        for url, prefix, instance, password in (
            ('', 'audit-shared', '1'*32, POSTGRES_PASSWORD),
            ('redis://audit-shared-redis:6379/0', '', '1'*32, POSTGRES_PASSWORD),
            ('redis://audit-shared-redis:6379/0', 'audit-shared', '', POSTGRES_PASSWORD),
            ('redis://audit-shared-redis:6379/0', 'audit-shared', '1'*32, None),
        ):
            self.assertNotEqual(
                self.resolve('blue',url,prefix,runtime_instance=instance,
                             postgres_password=password).returncode,
                0,
            )

    def test_managed_production_refuses_missing_trusted_ingress_settings(self):
        for missing in ('api_network_cidrs', 'trusted_ingress_cidrs'):
            with self.subTest(missing=missing):
                kwargs = {missing: None}
                result = self.resolve(
                    'blue', 'redis://audit-shared-redis:6379/0', managed=True, **kwargs
                )
                self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_production_forces_one_managed_postgres_credential_despite_caller_urls(self):
        result = self.resolve(
            'blue', 'redis://audit-shared-redis:6379/0', managed=True,
            database_url='postgresql+psycopg2://caller:caller@external.invalid:5432/caller',
            migration_database_url='postgresql+psycopg2://caller:caller@external.invalid:5432/caller',
        )
        self.assertEqual(result.returncode,0,result.stderr)
        services = json.loads(result.stdout)['services']
        self.assertEqual(services['pgbouncer']['environment']['DB_PASSWORD'],POSTGRES_PASSWORD)
        for role, host in (('initialize','audit-shared-postgres'),
                           ('backend','audit-config-blue-pooler'),
                           ('worker','audit-config-blue-pooler')):
            url = services[role]['environment']['DATABASE_URL']
            parsed = urlsplit(url)
            self.assertNotIn('external.invalid',url)
            self.assertEqual((parsed.username,parsed.password,parsed.hostname,parsed.port,parsed.path),
                             ('compiler',POSTGRES_PASSWORD,host,5432,'/compiler'))

    def test_local_deploy_like_mode_keeps_development_infrastructure(self):
        result = self.resolve('local','',production=False)
        self.assertEqual(result.returncode,0,result.stderr)
        services = json.loads(result.stdout)['services']
        self.assertIn('postgres',services)
        self.assertIn('redis',services)
        self.assertEqual(services['backend']['environment']['REDIS_URL'],'redis://redis:6379/0')

    def test_managed_pool_has_private_apis_scoped_controller_and_color_ports(self):
        for color, port in (('blue','18001'),('green','18002')):
            result = self.resolve(color,'redis://audit-shared-redis:6379/0',managed=True)
            self.assertEqual(result.returncode,0,result.stderr)
            config = json.loads(result.stdout)
            services = config['services']
            self.assertFalse(services['backend'].get('ports'))
            self.assertEqual(services['backend']['deploy']['replicas'],2)
            proxy, controller = services['api-proxy'],services['proxy-controller']
            self.assertEqual(proxy['ports'][0]['published'],port)
            self.assertEqual(proxy['ports'][0]['host_ip'],'127.0.0.1')
            self.assertEqual(controller['pid'],'service:api-proxy')
            self.assertEqual(controller['network_mode'],'service:api-proxy')
            self.assertEqual(controller['user'],proxy['user'])
            self.assertTrue(controller['read_only'])
            self.assertEqual(controller['cap_drop'],['ALL'])
            self.assertEqual([v['target'] for v in controller['volumes']],['/control'])
            self.assertTrue(proxy['volumes'][0]['read_only'])
            self.assertEqual(proxy['volumes'][0]['source'],'proxy_control')
            expected_instance = ('1' if color == 'blue' else '2') * 32
            self.assertEqual(config['volumes']['proxy_control']['name'],
                             'audit-config-'+color+'-proxy-'+'a'*40+'-'+expected_instance)
            self.assertEqual(controller['environment']['PROXY_POOL_ID'],'audit-config-'+color)
            self.assertEqual(services['backend']['environment']['TRUSTED_PROXY_CIDRS'], API_NETWORK_CIDRS)
            for role in ('proxy-control-init', 'proxy-controller'):
                self.assertEqual(
                    services[role]['environment']['PROXY_TRUSTED_INGRESS_CIDRS'],
                    TRUSTED_INGRESS_CIDRS,
                )
            expected_ownership = {
                'io.webcompiler.runtime.version': '1',
                'io.webcompiler.runtime.id': expected_instance,
                'io.webcompiler.runtime.pool': 'audit-config-'+color,
                'io.webcompiler.runtime.release': 'a'*40,
                'io.webcompiler.runtime.sandbox-pool': 'audit-shared-sandbox',
            }
            for role in ('backend','worker','frontend','pgbouncer','initialize',
                         'api-proxy','proxy-controller','proxy-control-init'):
                labels = services[role].get('labels')
                self.assertIsInstance(labels,dict)
                self.assertEqual(
                    {key: labels.get(key) for key in (*expected_ownership,
                                                       'io.webcompiler.runtime.role')},
                    {**expected_ownership, 'io.webcompiler.runtime.role': role},
                )
                self.assertNotEqual(labels['io.webcompiler.runtime.id'],'f'*32)
            for role in ('initialize','backend','worker','proxy-controller','proxy-control-init'):
                env = services[role]['environment']
                self.assertEqual(env['RUNTIME_INSTANCE_ID'],expected_instance)
                self.assertNotEqual(env['RUNTIME_INSTANCE_ID'],'f'*32)
            for role in ('backend','worker'):
                env = services[role]['environment']
                self.assertEqual(env['RUNTIME_POOL_ID'],'audit-config-'+color)
                self.assertNotEqual(env['RUNTIME_POOL_ID'],'caller-pool-must-not-win')
                self.assertEqual(env['SANDBOX_POOL_ID'],'audit-shared-sandbox')
            self.assertEqual(services['proxy-control-init']['network_mode'],'none')
            self.assertEqual(set(services['proxy-control-init']['cap_add']),{'CHOWN','DAC_OVERRIDE'})
            self.assertEqual(set(proxy['networks']),{'api_plane','frontend_plane','edge_ingress'})
            self.assertEqual(set(services['backend']['networks']),{'api_plane','shared_postgres'})
            self.assertEqual(set(services['frontend']['networks']),{'frontend_plane','edge_ingress'})
            self.assertEqual(services['frontend']['build']['args']['FRONTEND_API_UPSTREAM'],'api-proxy:8080')
            self.assertTrue(config['networks']['frontend_plane']['internal'])
            self.assertFalse(config['networks']['edge_ingress'].get('internal',False))
            self.assertEqual(config['networks']['edge_ingress']['driver_opts'],
                {'com.docker.network.bridge.host_binding_ipv4':'127.0.0.1'})
            self.assertEqual({name for name,service in services.items()
                if 'edge_ingress' in service.get('networks',{})},{'frontend','api-proxy'})
            self.assertTrue(config['networks']['api_plane']['external'])
            self.assertEqual(config['networks']['api_plane']['name'],'audit-config-'+color+'-api-plane')
            alias = 'audit-config-'+color+'-pooler'
            for role in ('worker','initialize','pgbouncer'):
                self.assertEqual(set(services[role]['networks']),{'shared_postgres'})
            self.assertIn(alias,services['pgbouncer']['networks']['shared_postgres']['aliases'])
            for role in ('backend','worker'):
                self.assertIn('@'+alias+':5432/',services[role]['environment']['DATABASE_URL'])


if __name__ == '__main__':
    unittest.main()
