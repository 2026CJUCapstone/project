"""Bounded CI builder cleanup never operates without an identity binding."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import yaml


ROOT = Path(__file__).resolve().parents[2]
CLEANUP = ROOT / "scripts" / "cleanup_ci_builder.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
BASH = shutil.which("bash")


class CleanupCIStaticTests(unittest.TestCase):
    def test_every_ci_builder_job_dispatches_bound_cleanup_script(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        source = CLEANUP.read_text(encoding="utf-8")

        jobs = yaml.safe_load(workflow)['jobs']
        builder_jobs = [(name, job) for name, job in jobs.items() if any(
            step.get('uses') == './.github/actions/setup-bounded-builder' for step in job['steps'])]
        self.assertTrue(builder_jobs)
        for name, job in builder_jobs:
            cleanup = [step for step in job['steps'] if step.get('run') == 'bash scripts/cleanup_ci_builder.sh']
            self.assertEqual(len(cleanup), 1)
            expected = ("${{ always() && steps.e2e-stack-cleanup.outcome == 'success' }}"
                        if name == 'e2e-stack' else 'always()')
            self.assertEqual(cleanup[0]['if'], expected)
            if name == 'e2e-stack':
                stack_cleanup = next(step for step in job['steps']
                                     if step.get('id') == 'e2e-stack-cleanup')
                self.assertEqual(stack_cleanup['run'], 'python3 scripts/e2e_stack_test.py --cleanup')
                self.assertLess(job['steps'].index(stack_cleanup), job['steps'].index(cleanup[0]))
        self.assertIn(
            'docker buildx rm --force "$WEBCOMPILER_BUILD_BUILDER"',
            source,
        )
        self.assertNotIn("docker buildx rm --force webcompiler-ci", source)
        self.assertNotIn("docker buildx rm --force webcompiler-ci", workflow)


@unittest.skipUnless(
    os.name == "posix" and BASH is not None,
    "CI builder cleanup execution requires a POSIX host with bash",
)
class CleanupCIRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="audit-ci-builder-")
        self.addCleanup(self.temp.cleanup)
        self.checkout = Path(self.temp.name) / "checkout"
        self.scripts = self.checkout / "scripts"
        self.bin = self.checkout / "bin"
        self.scripts.mkdir(parents=True)
        self.bin.mkdir()
        shutil.copy2(CLEANUP, self.scripts / "cleanup_ci_builder.sh")
        self.log = self.checkout / "calls.log"

        verifier = self.bin / "python3"
        verifier.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"python3 $*\" >> \"$AUDIT_CALL_LOG\"\n"
            "if [ \"${AUDIT_VERIFIER_MODE:-success}\" = fail ]; then exit 7; fi\n"
            "printf '%s\\n' \"${AUDIT_VERIFIED_ID:?}\"\n",
            encoding="utf-8",
        )
        verifier.chmod(0o700)
        docker = self.bin / "docker"
        docker.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"docker $*\" >> \"$AUDIT_CALL_LOG\"\n"
            "exit \"${AUDIT_DOCKER_STATUS:-0}\"\n",
            encoding="utf-8",
        )
        docker.chmod(0o700)

    def run_cleanup(
        self,
        *,
        builder=None,
        container_id=None,
        verifier_mode="success",
        verified_id=None,
        docker_status=0,
    ):
        environment = {
            "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
            "AUDIT_CALL_LOG": str(self.log),
            "AUDIT_VERIFIED_ID": verified_id or "a" * 64,
            "AUDIT_VERIFIER_MODE": verifier_mode,
            "AUDIT_DOCKER_STATUS": str(docker_status),
        }
        if builder is not None:
            environment["WEBCOMPILER_BUILD_BUILDER"] = builder
        if container_id is not None:
            environment["WEBCOMPILER_BUILD_CONTAINER_ID"] = container_id
        return subprocess.run(
            [BASH, str(self.scripts / "cleanup_ci_builder.sh")],
            cwd=self.checkout,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            check=False,
        )

    def call_lines(self):
        if not self.log.exists():
            return []
        return self.log.read_text(encoding="utf-8").splitlines()

    def test_missing_bound_id_skips_without_verifier_or_docker(self):
        result = self.run_cleanup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.call_lines(), [])

    def test_bad_ci_builder_name_is_rejected_without_docker(self):
        result = self.run_cleanup(builder="other-builder", container_id="a" * 64)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.call_lines(), [])

    def test_bad_bound_id_is_rejected_without_verifier_or_docker(self):
        result = self.run_cleanup(builder="webcompiler-ci", container_id="a" * 63)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.call_lines(), [])

    def test_verifier_failure_prevents_docker_cleanup(self):
        result = self.run_cleanup(
            builder="webcompiler-ci",
            container_id="a" * 64,
            verifier_mode="fail",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.call_lines()), 1)
        self.assertTrue(self.call_lines()[0].startswith("python3 "))

    def test_mismatched_verifier_identity_prevents_docker_cleanup(self):
        environment_id = "a" * 64
        result = self.run_cleanup(
            builder="webcompiler-ci",
            container_id=environment_id,
            verified_id="b" * 64,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.call_lines()), 1)
        self.assertTrue(self.call_lines()[0].startswith("python3 "))

    def test_exact_verified_binding_removes_only_ci_builder(self):
        result = self.run_cleanup(builder="webcompiler-ci", container_id="a" * 64)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.call_lines(), [
            "python3 "
            f"{self.scripts / 'verify_build_builder.py'}",
            "docker buildx rm --force webcompiler-ci",
        ])

    def test_docker_command_failure_is_propagated(self):
        result = self.run_cleanup(
            builder="webcompiler-ci",
            container_id="a" * 64,
            docker_status=9,
        )

        self.assertEqual(result.returncode, 9)
        self.assertEqual(self.call_lines()[-1], "docker buildx rm --force webcompiler-ci")


if __name__ == "__main__":
    unittest.main()
