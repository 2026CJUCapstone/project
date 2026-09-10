"""Real inherited flock contract; fresh temp files only, no Docker or SSH."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECK = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from edge_deploy import require_deploy_lock
require_deploy_lock(Path(sys.argv[2]))
'''


@unittest.skipUnless(sys.platform == 'linux' and all(shutil.which(x) for x in ('bash', 'flock')),
                     'Requires Linux bash/flock; no Docker required')
class EdgeDeployLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='audit-edge-lock-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root/'.deploy').mkdir()

    def run_child(self, setup, after=''):
        # Arguments, never interpolated paths or environment secrets.
        script = 'set -eu\n' + setup + '\n"$2" -c "$3" "$4" "$1"\n' + after
        return subprocess.run(['bash', '-c', script, 'edge-lock-fixture', str(self.root),
                               sys.executable, CHECK, str(ROOT/'scripts')],
                              capture_output=True, text=True, timeout=5)

    def test_parent_owned_lock_is_inherited_and_remains_held_after_child(self):
        result = self.run_child('exec 9>"$1/.deploy/deploy.lock"\nflock -n 9',
                                '! flock -n "$1/.deploy/deploy.lock" true')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unlocked_descriptor_is_not_parent_lock_proof(self):
        result = self.run_child('exec 9>"$1/.deploy/deploy.lock"')
        self.assertNotEqual(result.returncode, 0)

    def test_separately_opened_descriptor_cannot_borrow_another_holder(self):
        result = self.run_child('exec 8>"$1/.deploy/deploy.lock"\nflock -n 8\n'
                                'exec 9>"$1/.deploy/deploy.lock"')
        self.assertNotEqual(result.returncode, 0)

    def test_missing_wrong_path_and_symlink_are_rejected(self):
        for setup in ('exec 9>&-', 'exec 9>"$1/other.lock"\nflock -n 9'):
            with self.subTest(setup=setup):
                self.assertNotEqual(self.run_child(setup).returncode, 0)
        (self.root/'.deploy/deploy.lock').symlink_to(self.root/'other.lock')
        self.assertNotEqual(self.run_child('exec 9>"$1/.deploy/deploy.lock"\nflock -n 9').returncode, 0)


if __name__ == '__main__':
    unittest.main()
