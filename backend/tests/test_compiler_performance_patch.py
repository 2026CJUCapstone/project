import importlib.util
from pathlib import Path

import pytest


_PATCHER_PATH = Path(__file__).parents[2] / "runtime" / "compiler-patches" / "apply_performance.py"
_SPEC = importlib.util.spec_from_file_location("compiler_performance_patcher", _PATCHER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_PATCHER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PATCHER)


def _pinned_memory_shape() -> str:
    return """func bpp_gc_block_index_insert(block: *BppGcBlock) -> u64 {
    if (bpp_gc_block_index_ensure() == 0) { return 0; }
    return 1;
}

func bpp_gc_find_block(ptr: u64) -> *BppGcBlock {
    var indexed: *BppGcBlock = bpp_gc_block_index_find(ptr);
    if (indexed != 0) { return indexed; }
    var cur: *BppGcBlock = g_bpp_gc_blocks;
    return cur;
}

func bpp_gc_shutdown() -> u64 {
    g_bpp_gc_block_index_buckets = 0;
    g_bpp_gc_roots = (*BppGcRoot)0;
    return 1;
}
"""


def test_patch_memory_marks_failed_index_insert_incomplete_and_resets_only_at_gc_reset():
    patched = _PATCHER.patch_memory(_pinned_memory_shape())

    declaration = "var g_bpp_gc_block_index_incomplete: u64 = 0;\n\n"
    failed_insert = """    if (bpp_gc_block_index_ensure() == 0) {
        g_bpp_gc_block_index_incomplete = 1;
        return 0;
    }"""
    fast_miss = """    if (g_bpp_gc_block_index != 0 && g_bpp_gc_block_index_buckets != 0 &&
        g_bpp_gc_block_index_incomplete == 0) { return (*BppGcBlock)0; }"""
    fallback = "    var cur: *BppGcBlock = g_bpp_gc_blocks;"
    reset = """    g_bpp_gc_block_index_buckets = 0;
    g_bpp_gc_block_index_incomplete = 0;
    g_bpp_gc_roots = (*BppGcRoot)0;"""

    assert patched.index(declaration) < patched.index("func bpp_gc_block_index_insert")
    assert failed_insert in patched
    assert patched.index(failed_insert) < patched.index(fast_miss) < patched.index(fallback)
    # A negative lookup can return early only with a complete live index.  A
    # failed insertion reaches the original linear scan until GC reset clears it.
    assert fallback in patched
    assert reset in patched
    assert patched.count("g_bpp_gc_block_index_incomplete = 0;") == 1
    assert patched.index("g_bpp_gc_block_index_incomplete = 1;") < patched.index(
        "g_bpp_gc_block_index_incomplete = 0;", patched.index(failed_insert)
    )


def test_patch_memory_rejects_second_application():
    patched = _PATCHER.patch_memory(_pinned_memory_shape())

    with pytest.raises(ValueError, match="already applied"):
        _PATCHER.patch_memory(patched)


@pytest.mark.parametrize(
    "missing_anchor",
    [
        "func bpp_gc_block_index_insert(block: *BppGcBlock) -> u64 {",
        "    if (bpp_gc_block_index_ensure() == 0) { return 0; }",
        "    if (indexed != 0) { return indexed; }\n    var cur: *BppGcBlock = g_bpp_gc_blocks;",
        "    g_bpp_gc_block_index_buckets = 0;\n    g_bpp_gc_roots = (*BppGcRoot)0;",
    ],
)
def test_patch_memory_fails_closed_when_any_pinned_anchor_is_missing(missing_anchor: str):
    source = _pinned_memory_shape().replace(missing_anchor, "// changed pinned source", 1)

    with pytest.raises(ValueError, match="Pinned GC index source anchor mismatch"):
        _PATCHER.patch_memory(source)


def _graph_scope_shape() -> str:
    return """var g_exploration_validated_ctx: *SSAContext = 0;

func build_scope(prog: *AstProgram) -> *SSAContext {
    var ctx: *SSAContext = g_exploration_validated_ctx;
    if (ctx != 0) { return ctx; }
    return build_program(prog);
}

func validate_program_semantics(prog: *AstProgram) -> u64 {
    return 1;
}

func collect_codegen_roots(program: *AstProgram, used_names: *Vec) -> u64 {
    if (opt_get_level() < 1 && codegen_ssa_requested() == 0) { return 0; }
    var used_flags: u64 = 0;
    collect_used_func_names(program, used_names, &used_flags);
    var seed_implicit_codegen: u64 = codegen_ssa_requested() == 0;
    if (seed_implicit_codegen == 0 && (collected_flags & (CG_USED_HAS_METHOD_CALL | CG_USED_HAS_BINARY)) != 0) {
        return 0;
    }
    return 1;
}
"""


def test_patch_graph_scope_normalizes_crlf_and_keeps_semantic_validation_native_guards() -> None:
    extension = "func exploration_scope_context(ctx: *SSAContext, prog: *AstProgram) -> *SSAContext { return ctx; }"
    patched = _PATCHER.patch_graph_scope(_graph_scope_shape().replace("\n", "\r\n"), extension)

    assert "\r\n" not in patched
    assert patched.startswith(
        "import exploration_function_matches_source from ssa.dump;\n"
        "import op_of from ssa.core;\n"
        + extension
    )
    assert "if (ctx != 0) { return exploration_scope_context(ctx, prog); }" in patched
    assert "return build_program_used(prog, g_exploration_graph_names);" in patched
    assert """func validate_program_semantics(prog: *AstProgram) -> u64 {
    g_exploration_graph_names = 0;
    g_exploration_precise_native = 0;""" in patched
    # The cheap early return remains active for ordinary compilation; only the
    # unified graph request with a resolved root set reaches native closure.
    assert """if (opt_get_level() < 1 && codegen_ssa_requested() == 0 &&
        !(opt_get_output_mode() == OUT_UNIFIED_JSON && g_exploration_graph_names != 0)) { return 0; }""" in patched
    assert """if (opt_get_level() < 1 && opt_get_output_mode() == OUT_UNIFIED_JSON && g_exploration_graph_names != 0) {
        for (var i: u64 = 0; i < g_exploration_graph_names.len(); i++) {
            var name: *NameInfo = g_exploration_graph_names.get(i);
            used_add_resolved_name(used_names, slice(name.ptr, name.len));
        }
    }""" in patched
    assert """var precise_graph: u64 = opt_get_output_mode() == OUT_UNIFIED_JSON && g_exploration_precise_native != 0;
    var seed_implicit_codegen: u64 = codegen_ssa_requested() == 0 && precise_graph == 0;""" in patched
    assert "if (precise_graph == 0 && seed_implicit_codegen == 0" in patched

    with pytest.raises(ValueError, match="Pinned graph scope anchor mismatch"):
        _PATCHER.patch_graph_scope(patched, extension)


@pytest.mark.parametrize(
    "missing_anchor",
    [
        "var g_exploration_validated_ctx: *SSAContext = 0;",
        "    if (ctx != 0) { return ctx; }\n    return build_program(prog);",
        "func validate_program_semantics(prog: *AstProgram) -> u64 {",
        "    if (opt_get_level() < 1 && codegen_ssa_requested() == 0) { return 0; }",
        "    var used_flags: u64 = 0;\n    collect_used_func_names(program, used_names, &used_flags);",
        "    var seed_implicit_codegen: u64 = codegen_ssa_requested() == 0;",
        "    if (seed_implicit_codegen == 0 && (collected_flags & (CG_USED_HAS_METHOD_CALL | CG_USED_HAS_BINARY)) != 0) {",
    ],
)
def test_patch_graph_scope_fails_closed_when_any_pinned_anchor_is_missing(missing_anchor: str) -> None:
    source = _graph_scope_shape().replace(missing_anchor, "// changed pinned source", 1)

    with pytest.raises(ValueError, match="Pinned (graph scope|native root closure|implicit native roots) anchor mismatch"):
        _PATCHER.patch_graph_scope(source, "extension")


def _capture_shape() -> str:
    return """func capture(buf: *u8, len: u64) -> u64 {
    var bytes: *u8 = (*u8)buf;
    for (var i: u64 = 0; i < len; i++) {
        var c: u64 = bytes[i];
        if (c == 10) {
            asm_source_capture_finish_line();
        } else {
            asm_source_capture_append_byte(c);
        }
    }
    return 0;
}
"""


def test_patch_capture_normalizes_crlf_preserves_partial_writes_and_rejects_reapply() -> None:
    patched = _PATCHER.patch_capture(_capture_shape().replace("\n", "\r\n"))

    assert "\r\n" not in patched
    assert "for (var i: u64 = 0; i <= len; i++)" in patched
    assert "if (i != len && bytes[i] != 10) { continue; }" in patched
    assert "str_copy(g_asm_source_buf + g_asm_source_buf_len, buf + start, count);" in patched
    assert "if (i != len) { asm_source_capture_finish_line(); }" in patched
    assert "asm_source_capture_append_byte" not in patched

    with pytest.raises(ValueError, match="Pinned assembly capture anchor mismatch"):
        _PATCHER.patch_capture(patched)


def test_patch_capture_fails_closed_when_pinned_anchor_is_missing() -> None:
    source = _capture_shape().replace("asm_source_capture_finish_line();", "changed_capture();", 1)

    with pytest.raises(ValueError, match="Pinned assembly capture anchor mismatch"):
        _PATCHER.patch_capture(source)


def _native_json_shape() -> str:
    return """func parse_arg(arg: *u8, arg_len: u64) -> u64 {
        if (str_eq(slice(arg, arg_len), slice("--backend", str_len("--backend")))) {
            return 1;
        }
        return 0;
}

func emit_json(merged_prog: *AstProgram) -> u64 {
        asm_source_capture_start(1);
        program_with_sigs(merged_prog, get_func_sigs());
        asm_source_capture_stop();
        return 0;
}
"""


def test_patch_native_json_normalizes_crlf_and_tees_only_when_requested() -> None:
    patched = _PATCHER.patch_native_json(_native_json_shape().replace("\n", "\r\n"))

    assert "\r\n" not in patched
    assert patched.startswith("var g_exploration_native_asm: u64 = 0;\n")
    assert """if (str_eq(slice(arg, arg_len), slice("--native-asm-fd3", 16))) {
            g_exploration_native_asm = 1;
            continue;
        }""" in patched
    assert "if (str_eq(slice(arg, arg_len), slice(\"--backend\", str_len(\"--backend\")))) {" in patched
    # The regular JSON path keeps its capture target; fd 3 is used and restored
    # only when the opt-in launcher flag requested native assembly.
    assert "var previous_output: u64 = io_get_output_fd();" in patched
    assert "if (g_exploration_native_asm != 0) { io_set_output_fd(3); }" in patched
    assert "asm_source_capture_start(g_exploration_native_asm == 0);" in patched
    assert "if (g_exploration_native_asm != 0) { io_set_output_fd(previous_output); }" in patched
    assert patched.count("program_with_sigs(merged_prog, get_func_sigs());") == 1

    with pytest.raises(ValueError, match="Pinned native JSON tee anchor mismatch"):
        _PATCHER.patch_native_json(patched)


@pytest.mark.parametrize(
    "missing_anchor",
    [
        '        if (str_eq(slice(arg, arg_len), slice("--backend", str_len("--backend")))) {',
        """        asm_source_capture_start(1);
        program_with_sigs(merged_prog, get_func_sigs());
        asm_source_capture_stop();""",
    ],
)
def test_patch_native_json_fails_closed_when_any_pinned_anchor_is_missing(missing_anchor: str) -> None:
    source = _native_json_shape().replace(missing_anchor, "// changed pinned source", 1)

    with pytest.raises(ValueError, match="Pinned native JSON tee anchor mismatch"):
        _PATCHER.patch_native_json(source)


def test_patch_empty_string_normalizes_crlf_preserves_empty_guard_and_rejects_reapply() -> None:
    patched = _PATCHER.patch_empty_string("func emit() -> u64 {\r\n        emitln(\",0\");\r\n}\r\n")

    assert "\r\n" not in patched
    assert 'if (str_len > 2) { emit(","); }' in patched
    assert 'emitln("0");' in patched

    with pytest.raises(ValueError, match="Pinned empty string emission anchor mismatch"):
        _PATCHER.patch_empty_string(patched)


def test_patch_empty_string_fails_closed_when_pinned_anchor_is_missing() -> None:
    with pytest.raises(ValueError, match="Pinned empty string emission anchor mismatch"):
        _PATCHER.patch_empty_string('        emitln("0");')
