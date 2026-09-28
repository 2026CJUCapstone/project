"""Probe fidelity and cancellation tests; these do not prove Linux compatibility."""
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('node_probe_contract', Path(__file__).with_name('node_runtime_probe.py'))
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class NodeProbeContract(unittest.TestCase):
    def test_preserves_actual_final_alpine_runtime(self):
        source = (ROOT / 'runtime/docker/Dockerfile').read_text(encoding='utf-8')
        actual = probe.dockerfile_prefix(source)
        from_lines = [line for line in actual.splitlines() if line.startswith('FROM ')]
        self.assertEqual(len(from_lines), 3)
        self.assertTrue(from_lines[-1].endswith(' AS sandbox-runtime'))
        self.assertIn('COPY --from=bpp-build /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm', actual)
        self.assertNotIn('COPY --from=bpp-build /usr/local/bin/bpp ', actual)
        self.assertNotIn('/usr/local/share/verify_bpp_runtime.py', actual)
        self.assertNotIn('/usr/local/share/verify_bpp_exploration.py', actual)
        self.assertNotIn('git clone', actual)
        self.assertNotIn('compiler-patches', actual)
        self.assertIn('USER sandboxuser', actual)
        self.assertIn('RUN --network=none /bin/bash /audit/smoke.sh', actual)
        self.assertIn('ENTRYPOINT ["/usr/local/bin/run.sh"]', actual)
        self.assertNotIn('/bin/bash /usr/local/bin/run.sh', probe.SMOKE)
        self.assertIn('test "$(npm --version)" = 11.19.1', probe.SMOKE)

    def test_node_only_probe_rejects_bpp_copy_or_gate_drift(self):
        source=(ROOT/'runtime/docker/Dockerfile').read_text()
        for old in (
            'COPY --from=bpp-build /usr/local/bin/bpp',
            'COPY sandbox/verify_bpp_runtime.py',
            'COPY sandbox/verify_bpp_exploration.py',
            'RUN python3 -I /usr/local/share/verify_bpp_runtime.py',
            'RUN python3 -I /usr/local/share/verify_bpp_exploration.py',
        ):
            with self.subTest(instruction=old), self.assertRaises(ValueError):
                probe.dockerfile_prefix(source.replace(old,'# changed '+old,1))

    def test_rejects_missing_or_ambiguous_final_packaging(self):
        source = (ROOT / 'runtime/docker/Dockerfile').read_text(encoding='utf-8')
        for modified in (source.replace('\nWORKDIR /sandbox\n', '\nWORKDIR /elsewhere\n'), source + '\nWORKDIR /sandbox\n'):
            with self.subTest(source=modified[-40:]), self.assertRaises(ValueError):
                probe.dockerfile_prefix(modified)

    def test_rejects_missing_or_ambiguous_builder_boundary(self):
        source = (ROOT / 'runtime/docker/Dockerfile').read_text(encoding='utf-8')
        first = source.index('\nARG BPP_REPO=')
        for modified in (source[:first] + source[first:].replace('\nARG BPP_REPO=', '\nARG CHANGED=', 1),
                         source.replace('\nARG BPP_REPO=', '\nARG BPP_REPO=x\nARG BPP_REPO=', 1)):
            with self.subTest(source=modified[-40:]), self.assertRaises(ValueError):
                probe.dockerfile_prefix(modified)

    def test_rejects_stage_or_final_npm_copy_mismatch(self):
        source = (ROOT / 'runtime/docker/Dockerfile').read_text(encoding='utf-8')
        for modified in (
            source.replace('AS node-runtime', 'AS changed'),
            source.replace('AS bpp-build', 'AS changed'),
            source.replace('AS sandbox-runtime', 'AS changed'),
            source.replace('node:24.21.0-alpine@sha256:', 'ubuntu:26.04@sha256:'),
            source.replace('COPY --from=node-runtime ', 'COPY --from=changed '),
            source.replace('COPY --from=bpp-build /usr/local/lib/node_modules/npm ', 'COPY --from=changed /usr/local/lib/node_modules/npm '),
        ):
            with self.subTest(source=modified[:40]), self.assertRaises(ValueError):
                probe.dockerfile_prefix(modified)

    def test_abort_stops_only_owned_builder(self):
        for reason, free, limit in (('disk', 0, 900), ('deadline', 20 * 1024**3, -1)):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory:
                process = Mock(returncode=None)
                process.poll.return_value = None
                command = Mock()
                call = Mock(return_value=json.dumps([{'Config': {'Env': ['WEBCOMPILER_AUDIT_NONCE=testnonce']}}]))
                verify = Mock()
                with patch.object(probe.subprocess, 'Popen', return_value=process), patch.object(probe.shutil, 'disk_usage', return_value=SimpleNamespace(free=free)):
                    with self.assertRaisesRegex(AssertionError, 'safety floor|time exceeded'):
                        probe.run(self, source_root=ROOT, workdir=Path(directory), env={},
                            builder_name='fixture', container_id='immutable-owned-id', nonce='testnonce',
                            tag='fixture:node', command=command, call=call, verify=verify, limit=limit)
                process.terminate.assert_called_once()
                call.assert_called_once_with(['container', 'inspect', 'immutable-owned-id'])
                command.assert_called_once_with(['container', 'stop', '--time', '5', 'immutable-owned-id'], timeout=15)
                verify.assert_called_once()

    def test_cancellation_refuses_foreign_container(self):
        with tempfile.TemporaryDirectory() as directory:
            process = Mock(returncode=None)
            process.poll.return_value = None
            command = Mock()
            call = Mock(return_value=json.dumps([{'Config': {'Env': ['WEBCOMPILER_AUDIT_NONCE=someone-else']}}]))
            with patch.object(probe.subprocess, 'Popen', return_value=process), patch.object(probe.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
                with self.assertRaises(AssertionError):
                    probe.run(self, source_root=ROOT, workdir=Path(directory), env={},
                        builder_name='fixture', container_id='immutable-owned-id', nonce='testnonce',
                        tag='fixture:node', command=command, call=call, verify=Mock())
            command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
