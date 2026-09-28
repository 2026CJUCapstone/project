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
    var info_ptr: u64 = ssa_inst_aux_ptr(inst);
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

func dump_json(ctx: *SSAContext, with_phi: u64, stage: u64) -> u64 {
    var n: u64 = slice_len(funcs);
    for (var i: u64 = 0; i < n; i++) {
        if (i != 0) { emit(","); }
        var fn: *SSAFunction = funcs[i];
    }
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


def test_patcher_rejects_legacy_operand_pointer_contract():
    source = _pinned_shape().replace('ssa_inst_aux_ptr(inst)', 'operand_value(inst.src1)')
    with pytest.raises(ValueError, match='typed auxiliary'):
        _PATCHER.patch_source(source, 'extension')


def test_exploration_resolves_call_payloads_through_typed_table():
    extension = _PATCHER_PATH.with_name('exploration.bpp').read_text()
    assert extension.count('ssa_inst_aux_ptr(inst)') == 4
    assert 'operand_value(inst.src1)' not in extension
    assert 'op == SSA_OP_RET_SLICE_HEAP || op == SSA_OP_ASM' in extension


def test_filtered_functions_have_correct_json_separator_and_buffer_flush():
    patched = _PATCHER.patch_source(_pinned_shape(), 'extension')
    assert patched.index('exploration_function_matches_source(fn) == 0') < patched.index('if (first_function == 0)')
    # Nested IR/SSA must not disable the outer unified writer before ASM.
    # Standalone IR/SSA still flushes and restores unbuffered output.
    assert 'defer io_set_emit_buffering(opt_get_output_mode() == OUT_UNIFIED_JSON);' in patched
    assert 'if (i != 0) { emit(","); }' not in patched


def test_unified_buffering_fails_closed_and_restores_on_all_return_paths():
    source = 'func main_emit_unified_json_stdout(merged_prog: *AstProgram, ast_filter: *AstDumpFilter, source_file: u64, source_file_len: u64) -> u64 {\n    return 1;\n}'
    patched = _PATCHER.patch_main(source)
    assert 'io_set_emit_buffering(1);\n    defer io_set_emit_buffering(0);' in patched
    with pytest.raises(ValueError):
        _PATCHER.patch_main(patched)


def test_semantic_gate_is_preserved_and_reused_once_only_for_json_views():
    native = 'func native_compile() -> u64 { return 123; }\n'
    validation = '''func validate_program_semantics(prog: *AstProgram) -> u64 {
    if (prog == 0) { return 0; }
    typeinfo_set_structs(prog.structs_vec);
    typeinfo_set_funcs(prog.funcs_vec);
    var semantic_ctx: *SSAContext = build_program(prog);
    ssa_context_release_aux(semantic_ctx);
    if (diag_has_errors() != 0) { return 0; }
    return 1;
}'''
    source = native + validation + '''
func program_with_sigs_ir_json(prog: *AstProgram) -> u64 {
    build_program(prog);
    build_program(prog);
    build_program(prog);
}
func emit_program(prog: u64) -> u64 { return 456; }
'''
    patched = _PATCHER.patch_codegen(source)
    assert patched.startswith(native)
    assert patched.endswith('func emit_program(prog: u64) -> u64 { return 456; }\n')
    assert patched.count('exploration_take_validated_ctx(prog);') == 3
    assert 'var semantic_ctx: *SSAContext = build_program(prog);' in patched
    assert 'if (diag_has_errors() != 0) {\n        ssa_context_release_aux(semantic_ctx);\n        return 0;' in patched
    assert 'g_exploration_validated_ctx = 0;\n    if (ctx != 0) { return ctx; }' in patched
    assert 'opt_get_output_mode() == OUT_UNIFIED_JSON' in patched
    with pytest.raises(ValueError, match='semantic validation anchor'):
        _PATCHER.patch_codegen(patched)
