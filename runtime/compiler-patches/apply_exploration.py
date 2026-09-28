"""Strict additive source patch for pinned Bpp exploration JSON.

Kept in the web runtime build context so no mutable upstream branch is required.
Fails closed if the pinned source shape changes; never patches runtime binaries.
"""
from pathlib import Path
import argparse


def patch_source(source: str, extension: str) -> str:
    if "func exploration_emit_flow(" in source:
        raise ValueError("Exploration extension already applied; use a clean source checkout")
    source = source.replace("\r\n", "\n")
    if 'var info_ptr: u64 = ssa_inst_aux_ptr(inst);' not in source:
        raise ValueError("Pinned compiler must use typed auxiliary payloads")
    anchors = [
        ('func ssa_json_emit_inst(inst: *SSAInstruction, first: *u64) -> u64 {',
         extension + '\nfunc ssa_json_emit_inst(inst: *SSAInstruction, first: *u64) -> u64 {', 1),
        ('    emit("],\\\"sourceRanges\\\":");',
         '    emit("]");\n    exploration_emit_flow(inst);\n    emit(",\\\"sourceRanges\\\":");', 1),
        ('    ssa_json_emit_phi_args(inst);\n    emit(",\\\"sourceRanges\\\":");',
         '    ssa_json_emit_phi_args(inst);\n    exploration_emit_flow(inst);\n    emit(",\\\"sourceRanges\\\":");', 1),
        ('        ssa_json_escape(u8_slice_ptr(fn.name), u8_slice_len(fn.name));\n        emit(",\\\"blocks\\\":[");',
         '        ssa_json_escape(u8_slice_ptr(fn.name), u8_slice_len(fn.name));\n        exploration_emit_summary(fn);\n        emit(",\\\"blocks\\\":[");', 1),
        ('    var n: u64 = slice_len(funcs);\n    for (var i: u64 = 0; i < n; i++) {\n        if (i != 0) { emit(","); }\n        var fn: *SSAFunction = funcs[i];',
         '    var n: u64 = slice_len(funcs);\n    var first_function: u64 = 1;\n    for (var i: u64 = 0; i < n; i++) {\n        var fn: *SSAFunction = funcs[i];\n        if (exploration_function_matches_source(fn) == 0) { continue; }\n        if (first_function == 0) { emit(","); }\n        first_function = 0;', 1),
        ('func dump_json(ctx: *SSAContext, with_phi: u64, stage: u64) -> u64 {',
         'func dump_json(ctx: *SSAContext, with_phi: u64, stage: u64) -> u64 {\n    io_set_emit_buffering(1);\n    defer io_set_emit_buffering(0);', 1),
    ]
    for before, after, count in anchors:
        if source.count(before) != count:
            raise ValueError("Pinned compiler source does not match exploration patch anchor")
        source = source.replace(before, after)
    return source


def patch_main(source: str) -> str:
    source = source.replace("\r\n", "\n")
    anchor = 'func main_emit_unified_json_stdout(merged_prog: *AstProgram, ast_filter: *AstDumpFilter, source_file: u64, source_file_len: u64) -> u64 {'
    if source.count(anchor) != 1 or anchor + '\n    io_set_emit_buffering(1);' in source:
        raise ValueError("Pinned unified JSON buffering anchor mismatch")
    return source.replace(anchor, anchor + '\n    io_set_emit_buffering(1);\n    defer io_set_emit_buffering(0);')


def patch_codegen(source: str) -> str:
    """Reuse the full semantic gate's context for the first JSON view only.

    Validation still visits every function before any output; each view still
    runs its original transformations and releases its own auxiliary table.
    Native code generation and optimization choices are unchanged.
    """
    source = source.replace('\r\n', '\n')
    old = '''func validate_program_semantics(prog: *AstProgram) -> u64 {
    if (prog == 0) { return 0; }
    typeinfo_set_structs(prog.structs_vec);
    typeinfo_set_funcs(prog.funcs_vec);
    var semantic_ctx: *SSAContext = build_program(prog);
    ssa_context_release_aux(semantic_ctx);
    if (diag_has_errors() != 0) { return 0; }
    return 1;
}'''
    new = '''var g_exploration_validated_ctx: *SSAContext = 0;

func exploration_take_validated_ctx(prog: *AstProgram) -> *SSAContext {
    var ctx: *SSAContext = g_exploration_validated_ctx;
    g_exploration_validated_ctx = 0;
    if (ctx != 0) { return ctx; }
    return build_program(prog);
}

func validate_program_semantics(prog: *AstProgram) -> u64 {
    ssa_context_release_aux(g_exploration_validated_ctx);
    g_exploration_validated_ctx = 0;
    if (prog == 0) { return 0; }
    typeinfo_set_structs(prog.structs_vec);
    typeinfo_set_funcs(prog.funcs_vec);
    var semantic_ctx: *SSAContext = build_program(prog);
    if (diag_has_errors() != 0) {
        ssa_context_release_aux(semantic_ctx);
        return 0;
    }
    if (opt_get_output_mode() == OUT_UNIFIED_JSON &&
        (opt_get_unified_views() & (UNIFIED_VIEW_IR | UNIFIED_VIEW_SSA)) != 0) {
        g_exploration_validated_ctx = semantic_ctx;
    } else {
        ssa_context_release_aux(semantic_ctx);
    }
    return 1;
}'''
    if source.count(old) != 1:
        raise ValueError('Pinned full semantic validation anchor mismatch')
    source = source.replace(old, new)
    start = source.index('func program_with_sigs_ir_json(')
    end = source.index('\nfunc emit_program(', start)
    body = source[start:end]
    if body.count('build_program(prog)') != 3:
        raise ValueError('Pinned JSON view construction anchor mismatch')
    return source[:start] + body.replace('build_program(prog)', 'exploration_take_validated_ctx(prog)') + source[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compiler_root", type=Path)
    args = parser.parse_args()
    path = args.compiler_root / "src" / "ssa" / "dump.bpp"
    extension = Path(__file__).with_name("exploration.bpp").read_text(encoding="utf-8")
    result = patch_source(path.read_text(encoding="utf-8"), extension)
    main_path = args.compiler_root / 'src/main.bpp'
    main_result = patch_main(main_path.read_text(encoding='utf-8'))
    codegen_path = args.compiler_root / 'src/codegen.bpp'
    codegen_result = patch_codegen(codegen_path.read_text(encoding='utf-8'))
    path.write_text(result, encoding="utf-8", newline="\n")
    main_path.write_text(main_result, encoding='utf-8', newline='\n')
    codegen_path.write_text(codegen_result, encoding='utf-8', newline='\n')


if __name__ == "__main__":
    main()
