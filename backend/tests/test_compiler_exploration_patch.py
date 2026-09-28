import importlib.util
from pathlib import Path

import pytest


_PATCHER_PATH = Path(__file__).parents[2] / 'runtime' / 'compiler-patches' / 'apply_exploration.py'
_SPEC = importlib.util.spec_from_file_location('compiler_exploration_patcher', _PATCHER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_PATCHER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PATCHER)


def _pinned_shape() -> str:
    return r'''func ssa_json_emit_inst(inst: *SSAInstruction, first: *u64) -> u64 {
    if (normal != 0) {
    emit("],\"sourceRanges\":");
    }
    if (phi != 0) {
    ssa_json_emit_phi_args(inst);
    emit(",\"sourceRanges\":");
    }
}

func ssa_json_emit_func(fn: *SSAFunction) -> u64 {
        ssa_json_escape(u8_slice_ptr(fn.name), u8_slice_len(fn.name));
        emit(",\"blocks\":[");
}

func ssa_optimize(fn: *SSAFunction) -> u64 { return 0; }
'''


def test_patcher_inserts_normal_phi_and_summary_metadata_without_touching_optimization_passes():
    source = _pinned_shape()
    extension = 'func exploration_emit_flow(inst: *SSAInstruction) -> u64 { return 0; }'

    patched = _PATCHER.patch_source(source, extension)

    assert patched.startswith(f'{extension}\nfunc ssa_json_emit_inst')
    assert '    emit("]");\n    exploration_emit_flow(inst);\n    emit(",\\\"sourceRanges\\\":");' in patched
    assert '    ssa_json_emit_phi_args(inst);\n    exploration_emit_flow(inst);\n    emit(",\\\"sourceRanges\\\":");' in patched
    assert ('        ssa_json_escape(u8_slice_ptr(fn.name), u8_slice_len(fn.name));\n'
            '        exploration_emit_summary(fn);\n'
            '        emit(",\\\"blocks\\\":[");') in patched
    optimization_pass = 'func ssa_optimize(fn: *SSAFunction) -> u64 { return 0; }\n'
    assert patched[patched.index(optimization_pass):] == optimization_pass


def test_patcher_rejects_a_second_application():
    extension = 'func exploration_emit_flow(inst: *SSAInstruction) -> u64 { return 0; }'
    patched = _PATCHER.patch_source(_pinned_shape(), extension)

    with pytest.raises(ValueError, match='already applied'):
        _PATCHER.patch_source(patched, extension)


def test_patcher_fails_closed_when_a_pinned_anchor_is_missing():
    source = _pinned_shape().replace('ssa_json_emit_phi_args(inst);', 'different_phi_writer(inst);')

    with pytest.raises(ValueError, match='patch anchor'):
        _PATCHER.patch_source(source, 'func exploration_emit_flow(inst: *SSAInstruction) -> u64 { return 0; }')
