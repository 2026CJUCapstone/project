"""Real Git + flock only, in fresh temporary repositories. Never Docker/SSH.

Also runnable using stdlib unittest on an isolated Linux test host with no
pytest installation: python3 backend/tests/test_deploy_sync.py -v
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
SYNC = ROOT/'scripts/sync_remote_repo.sh'
GUARD = ROOT/'scripts/deploy_guard.sh'
MATERIALIZE = ROOT/'scripts/materialize_deploy_source.sh'


@unittest.skipUnless(os.name == 'posix' and all(shutil.which(x) for x in ('git','bash','flock')),
                     'Requires Linux Git/bash/flock, no Docker required')
class DeploySyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='audit-deploy-git-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.origin, self.checkout = self.base/'origin', self.base/'checkout'
        self.origin.mkdir()
        self.git(self.origin,'init','-b','main')
        self.git(self.origin,'config','user.name','Audit Fixture')
        self.git(self.origin,'config','user.email','fixture@example.invalid')
        (self.origin/'scripts').mkdir()
        (self.origin/'scripts/deploy_guard.sh').write_text(GUARD.read_text(),encoding='utf-8')
        # Only the exact real guard executes. Subsequent deploy side effects
        # are a marker and bounded wait, not the real Docker deploy script.
        (self.origin/'scripts/deploy_server.sh').write_text('''#!/usr/bin/env bash
set -euo pipefail
export PROJECT_ROOT="$(pwd -P)"
source "$PROJECT_ROOT/scripts/deploy_guard.sh"
git rev-parse HEAD > "$PROJECT_ROOT/.deploy/observed"
if [[ "${AUDIT_HOLD:-0}" == 1 ]]; then
  deadline=$((SECONDS + 15))
  while [[ ! -e "$PROJECT_ROOT/.deploy/release" ]]; do
    (( SECONDS < deadline )) || exit 1
    sleep 0.05
  done
fi
[[ "$(git rev-parse HEAD)" == "$DEPLOY_SHA" ]]
''',encoding='utf-8')
        (self.origin/'.gitignore').write_text('.deploy/\n.data/\n',encoding='utf-8')
        (self.origin/'version').write_text('first',encoding='utf-8')
        self.first = self.commit()
        (self.origin/'version').write_text('second',encoding='utf-8')
        self.second = self.commit()

    def git(self,path,*args):
        return subprocess.run(['git','-C',str(path),*args],check=True,
                              capture_output=True,text=True,timeout=10).stdout.strip()

    def commit(self):
        self.git(self.origin,'add','.')
        self.git(self.origin,'commit','-m','fixture')
        return self.git(self.origin,'rev-parse','HEAD')

    def environment(self,sha=None,**extra):
        return {**os.environ,'DEPLOY_SHA':sha or self.first,'DEPLOY_PATH':str(self.checkout),
                'DEPLOY_REPO':self.origin.as_uri(),'RUN_DEPLOY_SCRIPT':'1',
                'WEBCOMPILER_DEPLOY_LOCK_HELD':'0',**extra}

    def sync(self,sha=None,**extra):
        return subprocess.run(['bash',str(SYNC)],env=self.environment(sha,**extra),
                              capture_output=True,text=True,timeout=15)

    def test_fetches_exact_ci_sha_not_newer_main_and_reuses_lock_in_child(self):
        result = self.sync()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.git(self.checkout,'rev-parse','HEAD'),self.first)
        self.assertEqual((self.checkout/'.deploy/observed').read_text().strip(),self.first)
        self.assertEqual((self.checkout/'version').read_text(),'first')
        self.assertEqual(self.sync().returncode,0)

    def test_concurrent_sync_cannot_change_head_during_deploy(self):
        process = subprocess.Popen(['bash',str(SYNC)],env=self.environment(AUDIT_HOLD='1'),
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline = time.monotonic()+10
            while not (self.checkout/'.deploy/observed').exists():
                self.assertIsNone(process.poll())
                self.assertLess(time.monotonic(),deadline)
                time.sleep(.05)
            result = self.sync(self.second)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Another deployment',result.stderr)
            self.assertEqual(self.git(self.checkout,'rev-parse','HEAD'),self.first)
            (self.checkout/'.deploy/release').touch()
            _,error = process.communicate(timeout=10)
            self.assertEqual(process.returncode,0,error)
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=20)

    def test_preserves_dirty_tracked_and_untracked_files(self):
        self.assertEqual(self.sync().returncode,0)
        (self.checkout/'version').write_text('operator edit')
        (self.checkout/'operator-note').write_text('keep me')
        result = self.sync(self.second)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.checkout/'version').read_text(),'operator edit')
        self.assertEqual((self.checkout/'operator-note').read_text(),'keep me')
        self.assertEqual(self.git(self.checkout,'rev-parse','HEAD'),self.first)

    def test_preserves_ignored_runtime_state_across_successful_checkout(self):
        self.assertEqual(self.sync().returncode,0)
        data = self.checkout/'.data'
        data.mkdir()
        (data/'fixture.db').write_bytes(b'not a real database')
        (self.checkout/'operator-note').write_text('keep me')
        self.assertEqual(self.sync(self.second).returncode,0)
        self.assertEqual((data/'fixture.db').read_bytes(),b'not a real database')
        self.assertEqual((self.checkout/'operator-note').read_text(),'keep me')

    def test_refuses_staged_changes(self):
        self.assertEqual(self.sync().returncode,0)
        (self.checkout/'version').write_text('staged edit')
        self.git(self.checkout,'add','version')
        self.assertNotEqual(self.sync(self.second).returncode,0)
        self.assertEqual((self.checkout/'version').read_text(),'staged edit')

    def test_build_context_contains_only_verified_commit_not_worktree_extras(self):
        self.assertEqual(self.sync().returncode,0)
        (self.checkout/'operator-code.py').write_text('never build this')
        (self.checkout/'.env').write_text('never import this configuration')
        result = subprocess.run(['bash',str(MATERIALIZE)],
            env={**self.environment(),'PROJECT_ROOT':str(self.checkout)},
            capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        archive = Path(result.stdout.strip()).resolve()
        self.assertEqual(archive.parent,self.checkout/'.deploy')
        self.assertEqual((archive/'version').read_text(),'first')
        self.assertFalse((archive/'operator-code.py').exists())
        self.assertFalse((archive/'.env').exists())
        self.assertFalse((archive/'.git').exists())

    def test_refuses_checkout_that_would_overwrite_ignored_runtime_file(self):
        self.assertEqual(self.sync().returncode,0)
        data = self.checkout/'.data'
        data.mkdir()
        (data/'fixture.db').write_bytes(b'preserve operator data')
        (self.origin/'.data').mkdir()
        (self.origin/'.data/fixture.db').write_bytes(b'accidentally tracked')
        self.git(self.origin,'add','-f','.data/fixture.db')
        collision = self.commit()
        self.assertNotEqual(self.sync(collision).returncode,0)
        self.assertEqual((data/'fixture.db').read_bytes(),b'preserve operator data')

    def test_rejects_bad_sha_origin_and_missing_remote_commit(self):
        self.assertNotEqual(self.sync('main').returncode,0)
        self.assertFalse(self.checkout.exists())
        self.assertEqual(self.sync().returncode,0)
        self.assertNotEqual(self.sync('0'*40).returncode,0)
        result = self.sync(DEPLOY_REPO=(self.base/'other-origin').as_uri())
        self.assertNotEqual(result.returncode,0)
        self.assertIn('origin mismatch',result.stderr)
        self.assertEqual(self.git(self.checkout,'rev-parse','HEAD'),self.first)

    def test_guard_rejects_mismatched_head_and_forged_inherited_lock(self):
        self.assertEqual(self.sync().returncode,0)
        for extra in ({'DEPLOY_SHA':self.second},{'WEBCOMPILER_DEPLOY_LOCK_HELD':'1'}):
            result = subprocess.run(['bash','scripts/deploy_server.sh'],cwd=self.checkout,
                env=self.environment(**extra),capture_output=True,text=True,timeout=5)
            self.assertNotEqual(result.returncode,0)

    def test_lock_symlink_is_not_followed_or_truncated(self):
        self.checkout.mkdir()
        (self.checkout/'.deploy').mkdir()
        sentinel = self.base/'sentinel'
        sentinel.write_text('preserve')
        (self.checkout/'.deploy/deploy.lock').symlink_to(sentinel)
        self.assertNotEqual(self.sync().returncode,0)
        self.assertEqual(sentinel.read_text(),'preserve')

    def test_builder_uses_committed_compiler_pin_without_resolving_main(self):
        project = self.base/'builder'
        for folder in ('scripts','runtime/docker','runtime/sandbox','bin'):
            (project/folder).mkdir(parents=True)
        (project/'scripts/build_sandbox_image.sh').write_text((ROOT/'scripts/build_sandbox_image.sh').read_text())
        (project/'scripts/verify_build_builder.py').write_text("print('a'*64)\n")
        (project/'runtime/docker/Dockerfile').write_text('FROM scratch\n')
        (project/'runtime/sandbox/run.sh').write_text('# fixture\n')
        (project/'runtime/bpp-ref.txt').write_text(self.first+'\n')
        # Trusted CLI fakes only: a Git lookup would fail, and no real Docker
        # executable or daemon is reachable through this fixture invocation.
        for name,source in {
            'git':'#!/bin/sh\nexit 91\n',
            'docker':'#!/bin/sh\nprintf "%s\\n" "$@" > "$AUDIT_BUILD_ARGS"\n',
        }.items():
            path = project/'bin'/name
            path.write_text(source)
            path.chmod(0o700)
        args = project/'args'
        env = {**os.environ,'PATH':str(project/'bin')+os.pathsep+os.environ['PATH'],
               'BPP_REF':'','RUNTIME_BUILD_SIGNATURE':'','SANDBOX_IMAGE':'fixture-sandbox:fixed',
               'AUDIT_BUILD_ARGS':str(args),'WEBCOMPILER_BUILD_BUILDER':'fixture-builder'}
        result = subprocess.run(['bash',str(project/'scripts/build_sandbox_image.sh')],
            env=env,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('BPP_REF='+self.first,args.read_text())
        self.assertIn('fixture-sandbox:fixed',args.read_text())
        self.assertEqual(args.read_text().splitlines()[:6],['buildx','build','--builder','fixture-builder','--load','--shm-size=2g'])
        (project/'runtime/bpp-ref.txt').write_text('main')
        args.unlink()
        result = subprocess.run(['bash',str(project/'scripts/build_sandbox_image.sh')],
            env=env,capture_output=True,text=True,timeout=5)
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(args.exists())

    def test_updater_skips_while_deploy_lock_is_held_before_build_or_network(self):
        import fcntl
        self.assertEqual(self.sync().returncode,0)
        lock = self.checkout/'.deploy/deploy.lock'
        # Fixture lacks runtime build inputs: a premature signature calculation
        # (or network/build call) would fail instead of returning the busy path.
        with lock.open('a') as held:
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
            result = subprocess.run(['bash',str(ROOT/'scripts/update_sandbox_image_if_needed.sh')],
                env={**os.environ,'PROJECT_ROOT':str(self.checkout),
                     'WEBCOMPILER_DEPLOY_STATE_DIR':str(self.checkout/'.deploy')},
                capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('another deployment is already running; skipping update',result.stdout)


if __name__ == '__main__':
    unittest.main()
