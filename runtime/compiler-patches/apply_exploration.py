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
    ]
    for before, after, count in anchors:
        if source.count(before) != count:
            raise ValueError("Pinned compiler source does not match exploration patch anchor")
        source = source.replace(before, after)
    return source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compiler_root", type=Path)
    args = parser.parse_args()
    path = args.compiler_root / "src" / "ssa" / "dump.bpp"
    extension = Path(__file__).with_name("exploration.bpp").read_text(encoding="utf-8")
    result = patch_source(path.read_text(encoding="utf-8"), extension)
    path.write_text(result, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
