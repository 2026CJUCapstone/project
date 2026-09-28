"""Strict pinned compiler performance corrections (not validation bypasses).

An untracked allocation (e.g. a vector buffer) is a common negative lookup.
The old indexed lookup scanned every tracked allocation after every miss.
Only skip that fallback when all live allocations are known to be indexed;
retain the linear fallback after any failed index allocation/insertion.
Graph views reuse validation and project direct-call closures; unknown dispatch
keeps the full path. Native assembly is captured separately for the launcher's
mandatory assembly/link gate. All replacements reject mismatched/repeated input.
"""
from pathlib import Path


def patch_memory(source: str) -> str:
    source = source.replace("\r\n", "\n")
    if "g_bpp_gc_block_index_incomplete" in source:
        raise ValueError("GC lookup patch already applied")
    replacements = [
        (
            "func bpp_gc_block_index_insert(block: *BppGcBlock) -> u64 {",
            "var g_bpp_gc_block_index_incomplete: u64 = 0;\n\n"
            "func bpp_gc_block_index_insert(block: *BppGcBlock) -> u64 {",
        ),
        (
            "    if (bpp_gc_block_index_ensure() == 0) { return 0; }",
            "    if (bpp_gc_block_index_ensure() == 0) {\n"
            "        g_bpp_gc_block_index_incomplete = 1;\n"
            "        return 0;\n    }",
        ),
        (
            "    if (indexed != 0) { return indexed; }\n    var cur: *BppGcBlock = g_bpp_gc_blocks;",
            "    if (indexed != 0) { return indexed; }\n"
            "    if (g_bpp_gc_block_index != 0 && g_bpp_gc_block_index_buckets != 0 &&\n"
            "        g_bpp_gc_block_index_incomplete == 0) { return (*BppGcBlock)0; }\n"
            "    var cur: *BppGcBlock = g_bpp_gc_blocks;",
        ),
        (
            "    g_bpp_gc_block_index_buckets = 0;\n    g_bpp_gc_roots = (*BppGcRoot)0;",
            "    g_bpp_gc_block_index_buckets = 0;\n    g_bpp_gc_block_index_incomplete = 0;\n"
            "    g_bpp_gc_roots = (*BppGcRoot)0;",
        ),
    ]
    for before, after in replacements:
        if source.count(before) != 1:
            raise ValueError("Pinned GC index source anchor mismatch")
        source = source.replace(before, after)
    return source


def patch_graph_scope(source: str, extension: str) -> str:
    source = source.replace("\r\n", "\n")
    anchor = "var g_exploration_validated_ctx: *SSAContext = 0;"
    old = "    if (ctx != 0) { return ctx; }\n    return build_program(prog);"
    reset = "func validate_program_semantics(prog: *AstProgram) -> u64 {"
    if source.count(anchor) != 1 or source.count(old) != 1 or source.count(reset) != 1:
        raise ValueError("Pinned graph scope anchor mismatch")
    source = source.replace(anchor, extension + "\n" + anchor)
    source = source.replace(old, "    if (ctx != 0) { return exploration_scope_context(ctx, prog); }\n"
                            "    return build_program_used(prog, g_exploration_graph_names);")
    source = source.replace(reset, reset + "\n    g_exploration_graph_names = 0;\n    g_exploration_precise_native = 0;")
    # Source-only JSON still shows every user function. Native emitter root
    # closure retains all its implicit helpers, but need not emit unrelated
    # library bodies at O0. This does not turn on O1 transformations.
    guard = "    if (opt_get_level() < 1 && codegen_ssa_requested() == 0) { return 0; }"
    seed = "    var used_flags: u64 = 0;\n    collect_used_func_names(program, used_names, &used_flags);"
    if source.count(guard) != 1 or source.count(seed) != 1:
        raise ValueError("Pinned native root closure anchor mismatch")
    source = source.replace(guard, "    if (opt_get_level() < 1 && codegen_ssa_requested() == 0 &&\n"
                            "        !(opt_get_output_mode() == OUT_UNIFIED_JSON && g_exploration_graph_names != 0)) { return 0; }")
    source = source.replace(seed, '''    var used_flags: u64 = 0;
    if (opt_get_level() < 1 && opt_get_output_mode() == OUT_UNIFIED_JSON && g_exploration_graph_names != 0) {
        for (var i: u64 = 0; i < g_exploration_graph_names.len(); i++) {
            var name: *NameInfo = g_exploration_graph_names.get(i);
            used_add_resolved_name(used_names, slice(name.ptr, name.len));
        }
    }
    collect_used_func_names(program, used_names, &used_flags);''')
    implicit = "    var seed_implicit_codegen: u64 = codegen_ssa_requested() == 0;"
    strict = "    if (seed_implicit_codegen == 0 && (collected_flags & (CG_USED_HAS_METHOD_CALL | CG_USED_HAS_BINARY)) != 0) {"
    if source.count(implicit) != 1 or source.count(strict) != 1:
        raise ValueError("Pinned implicit native roots anchor mismatch")
    source = source.replace(implicit, "    var precise_graph: u64 = opt_get_output_mode() == OUT_UNIFIED_JSON && g_exploration_precise_native != 0;\n"
                            "    var seed_implicit_codegen: u64 = codegen_ssa_requested() == 0 && precise_graph == 0;")
    source = source.replace(strict, "    if (precise_graph == 0 && seed_implicit_codegen == 0 && (collected_flags & (CG_USED_HAS_METHOD_CALL | CG_USED_HAS_BINARY)) != 0) {")
    return "import exploration_function_matches_source from ssa.dump;\nimport op_of from ssa.core;\n" + source


def patch_capture(source: str) -> str:
    """Preserve line boundaries/partial writes, copy runs instead of each byte."""
    source = source.replace("\r\n", "\n")
    old = '''    var bytes: *u8 = (*u8)buf;
    for (var i: u64 = 0; i < len; i++) {
        var c: u64 = bytes[i];
        if (c == 10) {
            asm_source_capture_finish_line();
        } else {
            asm_source_capture_append_byte(c);
        }
    }
    return 0;
}'''
    new = '''    var bytes: *u8 = (*u8)buf;
    var start: u64 = 0;
    for (var i: u64 = 0; i <= len; i++) {
        if (i != len && bytes[i] != 10) { continue; }
        var count: u64 = i - start;
        if (count != 0) {
            asm_source_capture_reserve_buf(count);
            str_copy(g_asm_source_buf + g_asm_source_buf_len, buf + start, count);
            g_asm_source_buf_len = g_asm_source_buf_len + count;
        }
        if (i != len) { asm_source_capture_finish_line(); }
        start = i + 1;
    }
    return 0;
}'''
    if source.count(old) != 1:
        raise ValueError("Pinned assembly capture anchor mismatch")
    return source.replace(old, new)


def patch_native_json(source: str) -> str:
    """Tee the *unfiltered* native assembly to launcher-owned descriptor 3.

    The JSON retains its source-only ASM view. The launcher assembles/links the
    tee before releasing JSON, so semantic JSON is never treated as a native
    compilation success on its own. Normal CLI modes are unchanged.
    """
    source = source.replace("\r\n", "\n")
    old = '''        if (str_eq(slice(arg, arg_len), slice("--backend", str_len("--backend")))) {'''
    new = '''        if (str_eq(slice(arg, arg_len), slice("--native-asm-fd3", 16))) {
            g_exploration_native_asm = 1;
            continue;
        }
''' + old
    capture = '''        asm_source_capture_start(1);
        program_with_sigs(merged_prog, get_func_sigs());
        asm_source_capture_stop();'''
    tee = '''        var previous_output: u64 = io_get_output_fd();
        if (g_exploration_native_asm != 0) { io_set_output_fd(3); }
        asm_source_capture_start(g_exploration_native_asm == 0);
        program_with_sigs(merged_prog, get_func_sigs());
        asm_source_capture_stop();
        if (g_exploration_native_asm != 0) { io_set_output_fd(previous_output); }'''
    if source.count(old) != 1 or source.count(capture) != 1:
        raise ValueError("Pinned native JSON tee anchor mismatch")
    return "var g_exploration_native_asm: u64 = 0;\n" + source.replace(old, new).replace(capture, tee)


def patch_empty_string(source: str) -> str:
    source = source.replace("\r\n", "\n")
    old = '        emitln(",0");'
    if source.count(old) != 1:
        raise ValueError("Pinned empty string emission anchor mismatch")
    return source.replace(old, '        if (str_len > 2) { emit(","); }\n        emitln("0");')


def apply(root: Path) -> None:
    path = root / "src/std/mem.bpp"
    path.write_text(patch_memory(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    path = root / "src/codegen.bpp"
    extension = Path(__file__).with_name("graph_scope.bpp").read_text(encoding="utf-8")
    path.write_text(patch_graph_scope(path.read_text(encoding="utf-8"), extension), encoding="utf-8", newline="\n")
    path = root / "src/main.bpp"
    path.write_text(patch_native_json(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    path = root / "src/std/io.bpp"
    path.write_text(patch_capture(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    path = root / "src/emitter/emitter.bpp"
    path.write_text(patch_empty_string(path.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
