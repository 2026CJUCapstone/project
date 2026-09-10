"""Real backup/restore scripts against disposable DBs in the audit PostgreSQL.

No production connection, host port, service restart, or global cleanup. The
existing audit PostgreSQL memory/CPU limits also bound pg_dump/pg_restore.
"""
import io
import os
from pathlib import Path
import socket
import tarfile
from uuid import uuid4

import docker
import pytest


pytestmark = pytest.mark.skipif(os.getenv('RUN_SANDBOX_INTEGRATION') != '1',
    reason='Explicit isolated Docker audit environment required')


@pytest.mark.parametrize('directory_suffix', ['', '\r'])
def test_real_postgres_backup_restore_and_refusals(directory_suffix):
    client = docker.from_env(timeout=15)
    parent = client.containers.get(socket.gethostname())
    project = parent.labels.get('com.docker.compose.project', '')
    assert project.startswith('webcompiler-audit-')
    postgres = client.containers.list(filters={'label':[
        'com.docker.compose.project='+project, 'com.docker.compose.service=postgres']})
    assert len(postgres) == 1
    postgres = postgres[0]
    postgres.reload()
    assert 0 < postgres.attrs['HostConfig']['Memory'] <= 256*1024*1024
    assert 0 < postgres.attrs['HostConfig']['NanoCpus'] <= 250_000_000
    config = dict(item.split('=', 1) for item in postgres.attrs['Config']['Env'] if '=' in item)
    assert config['POSTGRES_DB'] == 'audit_stage' and config['POSTGRES_USER'] == 'audit_test'
    env = {'PGHOST':'127.0.0.1', 'PGUSER':config['POSTGRES_USER'],
           'PGPASSWORD':config['POSTGRES_PASSWORD'], 'PGCONNECT_TIMEOUT':'5'}
    token = uuid4().hex
    databases = []
    directory = '/tmp/audit_backup_'+token+directory_suffix
    source, target, rejected = ['audit_backup_'+role+'_'+token for role in ('src','dst','bad')]

    def execute(args):
        result = postgres.exec_run(args, environment=env)
        return result.exit_code, result.output.decode(errors='replace').replace(env['PGPASSWORD'], '[redacted]')

    def sql(database, statement):
        status, output = execute(['psql','--no-psqlrc','-At','-v','ON_ERROR_STOP=1',
                                  '--dbname='+database,'--command='+statement])
        assert status == 0, output
        return output.strip()

    def upload(files):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w') as archive:
            for name, content in files.items():
                assert '/' not in name and name in {'backup.sh','restore.sh','backup.dump.sha256'}
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(content), 0o600
                archive.addfile(info, io.BytesIO(content))
        data.seek(0)
        assert postgres.put_archive(directory, data.getvalue())

    try:
        assert execute(['mkdir','-m','700',directory])[0] == 0
        scripts = Path(__file__).resolve().parents[2]/'scripts'
        upload({name+'.sh':(scripts/(name+'_database.sh')).read_bytes().replace(b'\r\n',b'\n')
                for name in ('backup','restore')})
        for database in (source,target,rejected):
            assert database.startswith('audit_backup_') and database.endswith(token)
            sql('audit_stage', 'CREATE DATABASE "'+database+'"')
            databases.append(database)
        sql(source, "CREATE TABLE entries(id integer PRIMARY KEY, body text NOT NULL); "
                    "INSERT INTO entries VALUES (1,'한글 백업'), (2,'retained'); "
                    "CREATE TABLE scores(id integer REFERENCES entries(id), score integer); "
                    "INSERT INTO scores VALUES (1,100), (2,0)")
        snapshot_query = ("SELECT json_build_object('entries',(SELECT json_agg(e ORDER BY id) FROM entries e),"
                          "'scores',(SELECT json_agg(s ORDER BY id) FROM scores s))::text")
        expected = sql(source, snapshot_query)
        dump = directory+'/backup.dump'
        backup_command = ['sh',directory+'/backup.sh','--database',source,'--output',dump]
        code, output = execute(backup_command)
        assert code == 0, output
        code, output = execute(backup_command)
        assert code == 2 and 'overwrite' in output
        code, output = execute(['sh',directory+'/restore.sh','--database',target,'--backup',dump])
        assert code == 0, output
        assert sql(target, snapshot_query) == expected
        code, output = execute(['sh',directory+'/restore.sh','--database',target,'--backup',dump])
        assert code == 1 and 'non-empty' in output
        assert sql(target, snapshot_query) == expected
        upload({'backup.dump.sha256':('0'*64+'  backup.dump\n').encode()})
        code, output = execute(['sh',directory+'/restore.sh','--database',rejected,'--backup',dump])
        assert code == 1 and 'checksum verification failed' in output
        assert sql(rejected, "SELECT count(*) FROM pg_tables WHERE schemaname='public'") == '0'
    finally:
        for database in reversed(databases):
            assert database.startswith('audit_backup_') and database.endswith(token)
            sql('audit_stage', 'DROP DATABASE "'+database+'"')
        # Remove only explicit files created in this fixture's unique directory.
        assert directory.startswith('/tmp/audit_backup_'+token)
        execute(['rm','-f','--',*(directory+'/'+name for name in
                ('backup.sh','restore.sh','backup.dump','backup.dump.sha256'))])
        execute(['rmdir','--',directory])
        client.close()
