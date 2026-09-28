import copy
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
GATE_PATH = ROOT / 'runtime' / 'sandbox' / 'verify_bpp_exploration.py'
GATE_SPEC = importlib.util.spec_from_file_location('verify_bpp_exploration', GATE_PATH)
assert GATE_SPEC is not None and GATE_SPEC.loader is not None
GATE = importlib.util.module_from_spec(GATE_SPEC)
GATE_SPEC.loader.exec_module(GATE)


def _function(*, level: int, counters: tuple[int, int, int], call_uses: list[str] | None = None) -> dict:
    constant_operands, constant_branches, unreachable_blocks = counters
    instructions = [{
        'opcode': 'call',
        'valueFlow': {'version': 1, 'definitions': ['r7'], 'uses': call_uses or [], 'complete': True},
    }]
    return {
        'optimizationSummary': {
            'version': 1,
            'scope': 'function',
            'level': level,
            'constantOperands': constant_operands,
            'constantBranches': constant_branches,
            'unreachableBlocks': unreachable_blocks,
        },
        'blocks': [{'instructions': instructions}],
    }


def _nested_unified(function: dict) -> dict:
    return {'views': {'ssa': {'ssa': {'functions': [function]}}}}


def test_gate_accepts_nested_unified_o0_only_when_call_arguments_are_present():
    payload = _nested_unified(_function(level=0, counters=(0, 0, 0), call_uses=['r3']))

    GATE.validate(payload, optimized=False)

    no_arguments = copy.deepcopy(payload)
    no_arguments['views']['ssa']['ssa']['functions'][0]['blocks'][0]['instructions'][0]['valueFlow']['uses'] = []
    with pytest.raises(AssertionError, match='Call arguments'):
        GATE.validate(no_arguments, optimized=False)


def test_gate_accepts_direct_ssa_dump_o1_only_with_transformation_evidence():
    payload = {'ssa': {'functions': [_function(level=1, counters=(1, 0, 0))]}}

    GATE.validate(payload, optimized=True)

    no_evidence = copy.deepcopy(payload)
    no_evidence['ssa']['functions'][0]['optimizationSummary'].update({
        'constantOperands': 0,
        'constantBranches': 0,
        'unreachableBlocks': 0,
    })
    with pytest.raises(AssertionError, match='transformation evidence'):
        GATE.validate(no_evidence, optimized=True)


@pytest.mark.parametrize('optimized, mutate', [
    (False, lambda payload: payload['views']['ssa']['ssa']['functions'][0]['optimizationSummary'].update({'level': 1})),
    (False, lambda payload: payload['views']['ssa']['ssa']['functions'][0]['blocks'][0]['instructions'][0]['valueFlow'].update({'definitions': 'r7'})),
    (True, lambda payload: payload['views']['ssa']['ssa']['functions'][0]['optimizationSummary'].update({'constantOperands': 'one'})),
])
def test_gate_rejects_wrong_levels_and_malformed_exploration_metadata(optimized: bool, mutate):
    payload = _nested_unified(_function(
        level=1 if optimized else 0,
        counters=(1 if optimized else 0, 0, 0),
        call_uses=['r3'],
    ))
    mutate(payload)

    with pytest.raises((AssertionError, TypeError)):
        GATE.validate(payload, optimized=optimized)


def test_runtime_build_signatures_and_dockerfile_include_the_full_exploration_gate_chain():
    required_signature_inputs = (
        'runtime/sandbox/verify_bpp_exploration.py',
        'runtime/compiler-patches/apply_exploration.py',
        'runtime/compiler-patches/exploration.bpp',
    )
    for script_name in ('build_sandbox_image.sh', 'update_sandbox_image_if_needed.sh'):
        contents = (ROOT / 'scripts' / script_name).read_text(encoding='utf-8')
        for required in required_signature_inputs:
            assert required in contents

    dockerfile = (ROOT / 'runtime' / 'docker' / 'Dockerfile').read_text(encoding='utf-8')
    assert 'COPY compiler-patches /opt/compiler-patches' in dockerfile
    assert dockerfile.index('python3 /opt/compiler-patches/apply_exploration.py') < dockerfile.index('cmake -S . -B build-linux')
    assert 'COPY sandbox/verify_bpp_exploration.py /usr/local/share/verify_bpp_exploration.py' in dockerfile
    assert 'RUN python3 -I /usr/local/share/verify_bpp_exploration.py' in dockerfile
