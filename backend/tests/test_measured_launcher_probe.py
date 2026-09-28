"""The opt-in real-image probe must use the actual launcher protocol."""
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load(relative):
    spec = importlib.util.spec_from_file_location(Path(relative).stem, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_isolated_probe_uses_current_launcher_spec_and_pid_failure():
    probe = load('scripts/verify_measured_launcher.py')
    launcher = load('backend/app/services/linux_phase_launcher.py')
    limits = dict(cpuMs=1000,wallMs=3000,memoryBytes=96*1024**2,outputBytes=1024,pids=16,tmpBytes=4*1024**2)
    for code, _ in probe.CASES.values():
        value = probe.phase_spec(code, limits)
        assert launcher.validate_spec(value) == value
        assert value['version'] == 2
    assert probe.CASES['pids'][1] == 'process_limit_exceeded'
