from __future__ import annotations

import json
import re
from dataclasses import dataclass


FUNC_DECL_RE = re.compile(r"^\s*func\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE)
CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
CONTROL_KEYWORDS = {"if", "else", "while", "for", "switch", "match", "func", "return"}
BLOCK_RE = re.compile(r"^(b\d+):$")
BRANCH_RE = re.compile(r"^br\s+.+\?\s+(b\d+)\s+:\s+(b\d+)$")
JUMP_RE = re.compile(r"^jmp\s+(b\d+)$")


@dataclass(slots=True)
class _FunctionSection:
    compiled_name: str
    display_name: str
    lines: list[str]


def extract_user_function_names(source_code: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    for match in FUNC_DECL_RE.finditer(source_code):
        name = match.group(1)
        if name not in seen:
            names.append(name)
            seen.add(name)

    return names


def build_bpp_ast_graph(source_code: str) -> dict:
    clean_lines = [_strip_comment(line) for line in source_code.splitlines()]
    nodes: list[dict] = []
    edges: list[dict] = []
    node_index = 0
    node_lookup: dict[str, dict] = {}

    def add_node(
        node_type: str,
        label: str,
        *,
        parent: str | None = None,
        edge_label: str | None = None,
        line_no: int | None = None,
        raw: str | None = None,
    ) -> str:
        nonlocal node_index
        node_id = f"ast-{node_index}"
        node_index += 1

        node = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "children": [],
        }
        if line_no is not None:
            raw_text = raw or ""
            column = max(1, len(raw_text) - len(raw_text.lstrip()) + 1)
            node["sourceLocation"] = {
                "line": line_no,
                "column": column,
                "endLine": line_no,
                "endColumn": max(column, len(raw_text.rstrip()) + 1),
            }

        nodes.append(node)
        node_lookup[node_id] = node

        if parent is not None:
            edges.append({"from": parent, "to": node_id, "label": edge_label})
            node_lookup[parent]["children"].append(node_id)

        return node_id

    root_id = add_node("Program", "Program")
    parent_stack: list[str] = [root_id]

    for line_no, raw_line in enumerate(clean_lines, start=1):
        line = raw_line.strip()
        if not line:
            continue

        while line.startswith("}"):
            if len(parent_stack) > 1:
                parent_stack.pop()
            line = line[1:].strip()

        if not line:
            continue

        parent_id = parent_stack[-1]
        opened_body_id: str | None = None

        if match := re.match(r"^import\s+(.+?)\s+from\s+(.+);?$", line):
            add_node("ImportDecl", match.group(1).strip(), parent=parent_id, line_no=line_no, raw=raw_line)
        elif match := re.match(r"^func\s+([A-Za-z_]\w*)\s*\((.*?)\)", line):
            function_id = add_node("FunctionDecl", match.group(1), parent=root_id, line_no=line_no, raw=raw_line)
            signature = match.group(2).strip()
            if signature:
                add_node("Parameters", signature, parent=function_id, edge_label="params", line_no=line_no, raw=raw_line)
            opened_body_id = add_node("Block", "body", parent=function_id, edge_label="body", line_no=line_no, raw=raw_line)
        elif line.startswith("if " ) or line.startswith("if("):
            if_id = add_node("IfStatement", "if", parent=parent_id, line_no=line_no, raw=raw_line)
            add_node(
                "Condition",
                _extract_parenthesized(line) or "condition",
                parent=if_id,
                edge_label="condition",
                line_no=line_no,
                raw=raw_line,
            )
            opened_body_id = add_node("ThenBranch", "then", parent=if_id, edge_label="then", line_no=line_no, raw=raw_line)
        elif line.startswith("else if"):
            else_if_id = add_node("ElseIfStatement", "else if", parent=parent_id, line_no=line_no, raw=raw_line)
            add_node(
                "Condition",
                _extract_parenthesized(line) or "condition",
                parent=else_if_id,
                edge_label="condition",
                line_no=line_no,
                raw=raw_line,
            )
            opened_body_id = add_node("ThenBranch", "then", parent=else_if_id, edge_label="then", line_no=line_no, raw=raw_line)
        elif line.startswith("else"):
            opened_body_id = add_node("ElseBranch", "else", parent=parent_id, edge_label="else", line_no=line_no, raw=raw_line)
        elif line.startswith("while " ) or line.startswith("while("):
            loop_id = add_node("WhileStatement", "while", parent=parent_id, line_no=line_no, raw=raw_line)
            add_node(
                "Condition",
                _extract_parenthesized(line) or "condition",
                parent=loop_id,
                edge_label="condition",
                line_no=line_no,
                raw=raw_line,
            )
            opened_body_id = add_node("LoopBody", "body", parent=loop_id, edge_label="body", line_no=line_no, raw=raw_line)
        elif line.startswith("for " ) or line.startswith("for("):
            loop_id = add_node("ForStatement", "for", parent=parent_id, line_no=line_no, raw=raw_line)
            add_node(
                "Header",
                _extract_parenthesized(line) or "header",
                parent=loop_id,
                edge_label="header",
                line_no=line_no,
                raw=raw_line,
            )
            opened_body_id = add_node("LoopBody", "body", parent=loop_id, edge_label="body", line_no=line_no, raw=raw_line)
        elif line.startswith("return"):
            add_node("ReturnStatement", _normalize_statement(line, prefix="return"), parent=parent_id, line_no=line_no, raw=raw_line)
        elif line.startswith("var "):
            add_node("VariableDecl", _normalize_statement(line, prefix="var"), parent=parent_id, line_no=line_no, raw=raw_line)
        elif "=" in line and not any(op in line for op in ("==", "!=", ">=", "<=")):
            add_node("Assignment", _normalize_statement(line), parent=parent_id, line_no=line_no, raw=raw_line)
        elif call_name := _extract_call_name(line):
            add_node("CallExpression", call_name, parent=parent_id, line_no=line_no, raw=raw_line)
        else:
            add_node("Statement", _normalize_statement(line), parent=parent_id, line_no=line_no, raw=raw_line)

        if opened_body_id is not None and "{" in line:
            parent_stack.append(opened_body_id)

        trailing_closes = line.count("}")
        while trailing_closes > 0 and len(parent_stack) > 1:
            parent_stack.pop()
            trailing_closes -= 1

    return {"nodes": nodes, "edges": edges}


def build_bpp_ssa_graph(output: str, source_code: str) -> dict:
    sections = _split_function_sections(output, source_code)
    alias_map = {section.compiled_name: section.display_name for section in sections}
    blocks: list[dict] = []
    edges: list[dict] = []
    block_lookup: dict[str, dict] = {}

    for section in sections:
        current_block_id: str | None = None
        current_block_name: str | None = None
        current_lines: list[str] = []
        current_has_terminator = False

        def flush_block() -> None:
            nonlocal current_block_id, current_block_name, current_lines, current_has_terminator
            if current_block_id is None or current_block_name is None:
                return
            block = {
                "id": current_block_id,
                "label": f"{section.display_name} · {current_block_name}",
                "instructions": current_lines,
                "predecessors": [],
                "successors": [],
            }
            blocks.append(block)
            block_lookup[current_block_id] = block
            current_block_id = None
            current_block_name = None
            current_lines = []
            current_has_terminator = False

        for raw_line in section.lines[1:]:
            stripped = raw_line.strip()
            if not stripped:
                continue

            if block_match := BLOCK_RE.match(stripped):
                flush_block()
                current_block_name = block_match.group(1)
                current_block_id = f"{section.compiled_name}:{current_block_name}"
                continue

            if current_block_id is None:
                continue

            normalized = _replace_user_symbols(stripped, alias_map)
            current_lines.append(normalized)

            if current_has_terminator:
                continue

            if branch_match := BRANCH_RE.match(stripped):
                true_target = f"{section.compiled_name}:{branch_match.group(1)}"
                false_target = f"{section.compiled_name}:{branch_match.group(2)}"
                edges.append({"from": current_block_id, "to": true_target, "label": "True", "type": "true"})
                edges.append({"from": current_block_id, "to": false_target, "label": "False", "type": "false"})
                current_has_terminator = True
            elif jump_match := JUMP_RE.match(stripped):
                edges.append(
                    {
                        "from": current_block_id,
                        "to": f"{section.compiled_name}:{jump_match.group(1)}",
                        "label": None,
                        "type": "unconditional",
                    }
                )
                current_has_terminator = True
            elif stripped.startswith("ret"):
                current_has_terminator = True

        flush_block()

    for edge in edges:
        source = block_lookup.get(edge["from"])
        target = block_lookup.get(edge["to"])
        if source is not None:
            source["successors"].append(edge["to"])
        if target is not None:
            target["predecessors"].append(edge["from"])

    return {"blocks": blocks, "edges": edges}


def build_bpp_ir(output: str, source_code: str) -> dict:
    sections = _split_function_sections(output, source_code)
    alias_map = {section.compiled_name: section.display_name for section in sections}
    instructions: list[dict] = []
    line_index = 0

    for section_index, section in enumerate(sections):
        instructions.append(
            {
                "id": f"ir-{line_index}",
                "opcode": f"{section.display_name}:",
                "operands": [],
            }
        )
        line_index += 1

        for raw_line in section.lines[1:]:
            stripped = raw_line.strip()
            if not stripped:
                continue
            normalized = _replace_user_symbols(stripped, alias_map)
            instructions.append(_parse_ir_line(f"ir-{line_index}", normalized))
            line_index += 1

        if section_index < len(sections) - 1:
            instructions.append({"id": f"ir-{line_index}", "opcode": "", "operands": []})
            line_index += 1

    return {"instructions": instructions}


def build_bpp_asm(output: str, source_code: str) -> dict:
    source_names = extract_user_function_names(source_code)
    if not source_names:
        return {"lines": []}

    order_map = {name: index for index, name in enumerate(source_names)}
    sections: list[tuple[str, str, list[str]]] = []
    current_compiled_name: str | None = None
    current_display_name: str | None = None
    current_lines: list[str] = []

    for raw_line in output.splitlines():
        stripped = raw_line.strip()
        if stripped.endswith(":") and not stripped.startswith(".") and raw_line == raw_line.lstrip():
            label = stripped[:-1]
            display_name = _match_user_function(label, source_names)
            if current_compiled_name is not None:
                sections.append((current_compiled_name, current_display_name or current_compiled_name, current_lines))
            current_compiled_name = label
            current_display_name = display_name
            current_lines = [raw_line]
            continue

        if current_compiled_name is not None:
            current_lines.append(raw_line)

    if current_compiled_name is not None:
        sections.append((current_compiled_name, current_display_name or current_compiled_name, current_lines))

    filtered_sections = [
        (compiled_name, display_name, lines, index)
        for index, (compiled_name, display_name, lines) in enumerate(sections)
        if _match_user_function(compiled_name, source_names) is not None
    ]
    filtered_sections.sort(key=lambda item: (order_map.get(item[1], len(order_map)), item[3]))

    alias_map = {compiled_name: display_name for compiled_name, display_name, _, _ in filtered_sections}
    asm_lines: list[dict] = []

    for compiled_name, display_name, lines, _ in filtered_sections:
        asm_lines.append({"address": "", "label": display_name, "instruction": "", "operands": []})
        for raw_line in lines[1:]:
            stripped = raw_line.strip()
            if not stripped:
                continue
            if stripped.endswith(":"):
                asm_lines.append({"address": "", "label": stripped[:-1], "instruction": "", "operands": []})
                continue

            body, _, comment = stripped.partition(";")
            instruction_text = body.strip()
            if not instruction_text:
                continue

            parts = instruction_text.split(None, 1)
            instruction = parts[0]
            operand_text = parts[1] if len(parts) > 1 else ""
            operands = [_replace_user_symbols(item.strip(), alias_map) for item in operand_text.split(",") if item.strip()]
            asm_lines.append(
                {
                    "address": "",
                    "instruction": instruction,
                    "operands": operands,
                    "comment": comment.strip() or None,
                }
            )

    return {"lines": asm_lines}


def build_bpp_pipeline_from_json(
    output: str,
    source_code: str,
    source_filename: str | None = None,
    requested_targets: set[str] | None = None,
) -> dict | None:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    targets = requested_targets or {"ast", "ssa", "ir", "asm"}
    result: dict = {}
    semantics = payload.get("sourceRangeSemantics")
    if isinstance(semantics, dict):
        result["sourceRangeSemantics"] = semantics

    if "ast" in targets:
        ast_payload = _extract_view_payload(payload, "ast")
        if ast_payload is not None:
            ast_graph = build_bpp_ast_graph_from_json(ast_payload, source_filename)
            if ast_graph is not None:
                result["ast"] = ast_graph

    if "ssa" in targets:
        ssa_payload = _extract_view_payload(payload, "ssa")
        if ssa_payload is not None:
            ssa_graph = build_bpp_ssa_graph_from_json(ssa_payload, source_code, source_filename)
            if ssa_graph is not None:
                result["ssa"] = ssa_graph

    if "ir" in targets:
        ir_payload = _extract_view_payload(payload, "ir")
        if ir_payload is not None:
            ir_graph = build_bpp_ir_from_json(ir_payload, source_code, source_filename)
            if ir_graph is not None:
                result["ir"] = ir_graph

    if "asm" in targets:
        asm_graph = build_bpp_asm_from_json(output, source_filename)
        if asm_graph is not None:
            result["asm"] = asm_graph

    return result if any(key in result for key in ("ast", "ssa", "ir", "asm")) else None


def build_bpp_ast_graph_from_json(payload: dict, source_filename: str | None = None) -> dict | None:
    raw_nodes = payload.get("nodes")
    raw_edges = payload.get("edges")
    if not isinstance(raw_nodes, list):
        return None

    nodes: list[dict] = []
    edges: list[dict] = []
    node_lookup: dict[str, dict] = {}

    for index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, dict):
            continue
        node_id = _string_or_empty(raw_node.get("id") or raw_node.get("nodeId") or f"ast-json-{index}")
        node_type = _string_or_empty(raw_node.get("kind") or raw_node.get("type") or "Node")
        label = _string_or_empty(raw_node.get("label") or raw_node.get("name") or node_type)
        source_ranges = _normalize_source_ranges(raw_node.get("sourceRanges"), source_filename)
        raw_children = raw_node.get("children")
        children = [str(child) for child in raw_children if child is not None] if isinstance(raw_children, list) else []

        node: dict = {
            "id": node_id,
            "type": node_type,
            "label": label,
            "children": children,
        }
        if source_ranges:
            node["sourceRanges"] = source_ranges
            node["sourceLocation"] = _source_location_from_range(source_ranges[0])

        metadata = _copy_optional_fields(
            raw_node,
            (
                "module",
                "astKind",
                "astNodeId",
                "originNodeId",
                "rangeId",
                "generated",
                "generatedReason",
            ),
        )
        if metadata:
            node["metadata"] = metadata
        if "generated" in metadata:
            node["generated"] = bool(metadata["generated"])
        if metadata.get("generatedReason") is not None:
            node["generatedReason"] = metadata["generatedReason"]

        nodes.append(node)
        node_lookup[node_id] = node

    if isinstance(raw_edges, list):
        for index, raw_edge in enumerate(raw_edges):
            if not isinstance(raw_edge, dict):
                continue
            edge_from = _string_or_none(raw_edge.get("from") or raw_edge.get("source") or raw_edge.get("parent"))
            edge_to = _string_or_none(raw_edge.get("to") or raw_edge.get("target") or raw_edge.get("child"))
            if not edge_from or not edge_to:
                continue
            edge = {
                "from": edge_from,
                "to": edge_to,
                "label": _string_or_none(raw_edge.get("label")),
                "type": _string_or_none(raw_edge.get("type")),
            }
            edges.append(edge)
            if edge_from in node_lookup and edge_to not in node_lookup[edge_from]["children"]:
                node_lookup[edge_from]["children"].append(edge_to)

    # Some compiler snapshots only carry parent/children on nodes.
    existing_edges = {(edge["from"], edge["to"]) for edge in edges}
    for node in nodes:
        raw_children = node.get("children")
        if not isinstance(raw_children, list):
            continue
        for child_id in raw_children:
            child_text = _string_or_none(child_id)
            if child_text and (node["id"], child_text) not in existing_edges:
                edges.append({"from": node["id"], "to": child_text, "label": None, "type": None})
                existing_edges.add((node["id"], child_text))

    return {"nodes": nodes, "edges": edges}


def build_bpp_ssa_graph_from_json(payload: dict, source_code: str, source_filename: str | None = None) -> dict | None:
    ssa_payload = payload.get("ssa") if isinstance(payload.get("ssa"), dict) else payload
    raw_functions = ssa_payload.get("functions") if isinstance(ssa_payload, dict) else None
    if not isinstance(raw_functions, list):
        return None

    source_names = extract_user_function_names(source_code)
    blocks: list[dict] = []
    edges: list[dict] = []
    block_lookup: dict[str, dict] = {}

    for function_index, raw_function in enumerate(raw_functions):
        if not isinstance(raw_function, dict):
            continue
        raw_blocks = raw_function.get("blocks")
        if not isinstance(raw_blocks, list):
            continue

        compiled_name = _string_or_empty(raw_function.get("name") or raw_function.get("id") or f"func{function_index}")
        display_name = _match_user_function(compiled_name, source_names) or compiled_name
        if not _json_function_has_source_ranges(raw_function, source_filename) and _match_user_function(compiled_name, source_names) is None:
            continue

        block_id_map: dict[str, str] = {}
        for block_index, raw_block in enumerate(raw_blocks):
            if not isinstance(raw_block, dict):
                continue
            raw_block_id = _string_or_empty(raw_block.get("id") or f"b{block_index}")
            block_id = f"{compiled_name}:{raw_block_id}"
            block_id_map[raw_block_id] = block_id

        for block_index, raw_block in enumerate(raw_blocks):
            if not isinstance(raw_block, dict):
                continue
            raw_block_id = _string_or_empty(raw_block.get("id") or f"b{block_index}")
            block_id = block_id_map[raw_block_id]
            raw_instructions = raw_block.get("instructions")
            instruction_items = raw_instructions if isinstance(raw_instructions, list) else []
            instruction_lines: list[str] = []
            instruction_source_ranges: list[list[dict]] = []
            instruction_ids: list[str] = []

            for instruction_index, raw_instruction in enumerate(instruction_items):
                instruction_lines.append(_format_json_instruction(raw_instruction))
                instruction_source_ranges.append(_normalize_source_ranges(_dict_get(raw_instruction, "sourceRanges"), source_filename))
                instruction_ids.append(_string_or_empty(_dict_get(raw_instruction, "id") or f"{block_id}:i{instruction_index}"))

            block = {
                "id": block_id,
                "label": f"{display_name} · {raw_block_id}",
                "instructions": instruction_lines,
                "instructionSourceRanges": instruction_source_ranges,
                "instructionIds": instruction_ids,
                "sourceRanges": _normalize_source_ranges(raw_block.get("sourceRanges"), source_filename),
                "predecessors": [],
                "successors": [],
            }
            block_meta = _copy_optional_fields(raw_block, ("generated", "generatedReason"))
            if block_meta:
                block["metadata"] = block_meta
                if "generated" in block_meta:
                    block["generated"] = bool(block_meta["generated"])
                if block_meta.get("generatedReason") is not None:
                    block["generatedReason"] = block_meta["generatedReason"]

            blocks.append(block)
            block_lookup[block_id] = block

            for raw_instruction in instruction_items:
                for edge in _edges_from_ssa_instruction(raw_instruction, block_id, compiled_name, block_id_map):
                    edges.append(edge)

    edge_keys: set[tuple[str, str, str]] = set()
    deduped_edges: list[dict] = []
    for edge in edges:
        key = (edge["from"], edge["to"], edge.get("type") or "")
        if key in edge_keys:
            continue
        edge_keys.add(key)
        deduped_edges.append(edge)

    for edge in deduped_edges:
        source = block_lookup.get(edge["from"])
        target = block_lookup.get(edge["to"])
        if source is not None and edge["to"] not in source["successors"]:
            source["successors"].append(edge["to"])
        if target is not None and edge["from"] not in target["predecessors"]:
            target["predecessors"].append(edge["from"])

    return {"blocks": blocks, "edges": deduped_edges}


def build_bpp_ir_from_json(payload: dict, source_code: str, source_filename: str | None = None) -> dict | None:
    ir_payload = payload.get("ir") if isinstance(payload.get("ir"), dict) else payload
    if not isinstance(ir_payload, dict):
        return None

    source_names = extract_user_function_names(source_code)
    instructions: list[dict] = []
    raw_instructions = ir_payload.get("instructions")
    if isinstance(raw_instructions, list):
        for index, raw_instruction in enumerate(raw_instructions):
            instructions.append(_normalize_json_ir_instruction(raw_instruction, f"ir-{index}", source_filename))
        return {"instructions": instructions}

    raw_functions = ir_payload.get("functions")
    if not isinstance(raw_functions, list):
        return None

    line_index = 0
    for function_index, raw_function in enumerate(raw_functions):
        if not isinstance(raw_function, dict):
            continue
        compiled_name = _string_or_empty(raw_function.get("name") or raw_function.get("id") or f"func{function_index}")
        display_name = _match_user_function(compiled_name, source_names) or compiled_name
        if not _json_function_has_source_ranges(raw_function, source_filename) and _match_user_function(compiled_name, source_names) is None:
            continue

        instructions.append({"id": f"ir-{line_index}", "opcode": f"{display_name}:", "operands": []})
        line_index += 1

        raw_blocks = raw_function.get("blocks")
        if isinstance(raw_blocks, list):
            for raw_block in raw_blocks:
                if not isinstance(raw_block, dict):
                    continue
                block_name = _string_or_none(raw_block.get("id") or raw_block.get("label"))
                if block_name:
                    instructions.append(
                        {
                            "id": f"ir-{line_index}",
                            "opcode": f"{block_name}:",
                            "operands": [],
                            "sourceRanges": _normalize_source_ranges(raw_block.get("sourceRanges"), source_filename),
                        }
                    )
                    line_index += 1
                block_instructions = raw_block.get("instructions")
                if isinstance(block_instructions, list):
                    for raw_instruction in block_instructions:
                        instructions.append(_normalize_json_ir_instruction(raw_instruction, f"ir-{line_index}", source_filename))
                        line_index += 1
        else:
            function_instructions = raw_function.get("instructions")
            if isinstance(function_instructions, list):
                for raw_instruction in function_instructions:
                    instructions.append(_normalize_json_ir_instruction(raw_instruction, f"ir-{line_index}", source_filename))
                    line_index += 1

    return {"instructions": instructions}


def build_bpp_asm_from_json(output: str, source_filename: str | None = None) -> dict | None:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    asm_payload = _extract_view_payload(payload, "asm")
    if isinstance(asm_payload, dict) and isinstance(asm_payload.get("asm"), dict):
        asm_payload = asm_payload.get("asm")
    raw_lines = asm_payload.get("lines") if isinstance(asm_payload, dict) else None
    if not isinstance(raw_lines, list):
        return None

    lines: list[dict] = []
    for raw_line in raw_lines:
        if not isinstance(raw_line, dict):
            continue

        text = _string_or_empty(raw_line.get("text"))
        instruction = _string_or_empty(raw_line.get("instruction"))
        raw_operands = raw_line.get("operands")
        operands = [str(item) for item in raw_operands if item is not None] if isinstance(raw_operands, list) else []
        label = _string_or_none(raw_line.get("label"))
        if label is None and not instruction and text.strip().endswith(":"):
            label = text.strip()[:-1]

        line: dict = {
            "address": _string_or_empty(raw_line.get("address")),
            "label": label,
            "instruction": instruction,
            "operands": operands,
            "comment": _string_or_none(raw_line.get("comment")),
            "text": text,
            "sourceRanges": _normalize_source_ranges(raw_line.get("sourceRanges"), source_filename),
        }
        for key in ("generated", "generatedReason", "ssaInstructionIds", "segments"):
            if key in raw_line:
                line[key] = raw_line[key]
        lines.append(line)

    if source_filename:
        lines = _filter_asm_lines_to_source_sections(lines)

    return {"lines": lines}


def _extract_view_payload(payload: dict, view_name: str) -> dict | None:
    views = payload.get("views")
    if isinstance(views, dict) and isinstance(views.get(view_name), dict):
        return views[view_name]

    view_payload = payload.get(view_name)
    if isinstance(view_payload, dict):
        return payload if view_name == "asm" else view_payload

    if view_name == "ast" and isinstance(payload.get("nodes"), list):
        return payload
    if view_name == "ssa" and isinstance(payload.get("ssa"), dict):
        return payload
    if view_name == "ir" and (isinstance(payload.get("ir"), dict) or isinstance(payload.get("instructions"), list)):
        return payload
    if view_name == "asm" and isinstance(payload.get("asm"), dict):
        return payload
    return None


def _source_location_from_range(source_range: dict) -> dict:
    return {
        "line": source_range["startLine"],
        "column": source_range["startColumn"],
        "endLine": source_range["endLine"],
        "endColumn": source_range["endColumn"],
    }


def _copy_optional_fields(source: dict, keys: tuple[str, ...]) -> dict:
    return {key: source[key] for key in keys if key in source}


def _dict_get(value: object, key: str) -> object | None:
    if isinstance(value, dict):
        return value.get(key)
    return None


def _json_function_has_source_ranges(raw_function: dict, source_filename: str | None) -> bool:
    if _normalize_source_ranges(raw_function.get("sourceRanges"), source_filename):
        return True
    raw_blocks = raw_function.get("blocks")
    if not isinstance(raw_blocks, list):
        return False
    for raw_block in raw_blocks:
        if not isinstance(raw_block, dict):
            continue
        if _normalize_source_ranges(raw_block.get("sourceRanges"), source_filename):
            return True
        raw_instructions = raw_block.get("instructions")
        if not isinstance(raw_instructions, list):
            continue
        for raw_instruction in raw_instructions:
            if _normalize_source_ranges(_dict_get(raw_instruction, "sourceRanges"), source_filename):
                return True
    return False


def _format_json_instruction(raw_instruction: object) -> str:
    if isinstance(raw_instruction, str):
        return raw_instruction.strip()
    if not isinstance(raw_instruction, dict):
        return _string_or_empty(raw_instruction)

    text = _string_or_none(raw_instruction.get("text") or raw_instruction.get("display") or raw_instruction.get("dump"))
    if text:
        return text.strip()

    opcode = _string_or_empty(raw_instruction.get("opcode") or raw_instruction.get("kind"))
    result = raw_instruction.get("result")
    operands = raw_instruction.get("operands")
    operand_text = ""
    if isinstance(operands, list) and operands:
        operand_text = " " + ", ".join(_format_json_value(item) for item in operands)

    prefix = f"{_format_json_value(result)} = " if result is not None else ""
    return f"{prefix}{opcode}{operand_text}".strip()


def _format_json_value(value: object) -> str:
    if isinstance(value, dict):
        kind = _string_or_none(value.get("kind"))
        raw_id = value.get("id")
        raw_value = value.get("value")
        raw_name = value.get("name")
        if kind == "reg" and raw_id is not None:
            return f"r{raw_id}"
        if kind == "block" and raw_id is not None:
            return f"b{raw_id}"
        if kind == "const" and raw_value is not None:
            return f"#{raw_value}"
        if raw_name is not None:
            return str(raw_name)
        if raw_id is not None:
            return str(raw_id)
        if raw_value is not None:
            return str(raw_value)
    if isinstance(value, list):
        return "[" + ", ".join(_format_json_value(item) for item in value) + "]"
    if value is None:
        return ""
    return str(value)


def _edges_from_ssa_instruction(
    raw_instruction: object,
    current_block_id: str,
    compiled_name: str,
    block_id_map: dict[str, str],
) -> list[dict]:
    if not isinstance(raw_instruction, dict):
        return []
    opcode = _string_or_empty(raw_instruction.get("opcode"))
    operands = raw_instruction.get("operands")
    if not isinstance(operands, list):
        return []

    def block_target(operand: object) -> str | None:
        if isinstance(operand, dict):
            raw_value = operand.get("value", operand.get("id"))
            if raw_value is None:
                return None
            raw_text = str(raw_value)
            raw_block_id = raw_text if raw_text.startswith("b") else f"b{raw_text}"
        else:
            raw_text = str(operand)
            raw_block_id = raw_text if raw_text.startswith("b") else f"b{raw_text}"
        return block_id_map.get(raw_block_id) or f"{compiled_name}:{raw_block_id}"

    if opcode == "br" and len(operands) >= 3:
        true_target = block_target(operands[1])
        false_target = block_target(operands[2])
        edges: list[dict] = []
        if true_target:
            edges.append({"from": current_block_id, "to": true_target, "label": "True", "type": "true"})
        if false_target:
            edges.append({"from": current_block_id, "to": false_target, "label": "False", "type": "false"})
        return edges

    if opcode == "jmp" and operands:
        target = block_target(operands[0])
        if target:
            return [{"from": current_block_id, "to": target, "label": None, "type": "unconditional"}]

    return []


def _normalize_json_ir_instruction(raw_instruction: object, fallback_id: str, source_filename: str | None) -> dict:
    if isinstance(raw_instruction, str):
        parsed = _parse_ir_line(fallback_id, raw_instruction)
        return parsed
    if not isinstance(raw_instruction, dict):
        return {"id": fallback_id, "opcode": _string_or_empty(raw_instruction), "operands": []}

    text = _string_or_none(raw_instruction.get("text") or raw_instruction.get("display") or raw_instruction.get("dump"))
    if text:
        parsed = _parse_ir_line(_string_or_empty(raw_instruction.get("id") or fallback_id), text)
    else:
        raw_operands = raw_instruction.get("operands")
        parsed = {
            "id": _string_or_empty(raw_instruction.get("id") or fallback_id),
            "opcode": _string_or_empty(raw_instruction.get("opcode") or raw_instruction.get("kind")),
            "operands": [_format_json_value(item) for item in raw_operands] if isinstance(raw_operands, list) else [],
        }
        if raw_instruction.get("result") is not None:
            parsed["result"] = _format_json_value(raw_instruction.get("result"))
        if raw_instruction.get("comment") is not None:
            parsed["comment"] = _string_or_none(raw_instruction.get("comment"))

    parsed["sourceRanges"] = _normalize_source_ranges(raw_instruction.get("sourceRanges"), source_filename)
    for key in ("generated", "generatedReason", "ssaInstructionIds", "segments", "astNodeIds"):
        if key in raw_instruction:
            parsed[key] = raw_instruction[key]
    return parsed


def _split_function_sections(output: str, source_code: str) -> list[_FunctionSection]:
    source_names = extract_user_function_names(source_code)
    if not source_names:
        return []

    order_map = {name: index for index, name in enumerate(source_names)}
    raw_sections: list[tuple[str, list[str]]] = []
    current_name: str | None = None
    current_lines: list[str] = []

    for raw_line in output.splitlines():
        if raw_line.startswith("func "):
            if current_name is not None:
                raw_sections.append((current_name, current_lines))
            current_name = raw_line[5:].strip()
            current_lines = [raw_line]
            continue

        if current_name is not None:
            current_lines.append(raw_line)

    if current_name is not None:
        raw_sections.append((current_name, current_lines))

    sections: list[tuple[int, _FunctionSection]] = []
    for index, (compiled_name, lines) in enumerate(raw_sections):
        display_name = _match_user_function(compiled_name, source_names)
        if display_name is None:
            continue
        sections.append((index, _FunctionSection(compiled_name=compiled_name, display_name=display_name, lines=lines)))

    sections.sort(key=lambda item: (order_map.get(item[1].display_name, len(order_map)), item[0]))
    return [section for _, section in sections]


def _match_user_function(compiled_name: str, source_names: list[str]) -> str | None:
    if compiled_name in source_names:
        return compiled_name

    for name in source_names:
        if compiled_name.endswith(f"__{name}"):
            return name

    return None


def _replace_user_symbols(text: str, alias_map: dict[str, str]) -> str:
    normalized = text
    for compiled_name, display_name in alias_map.items():
        normalized = normalized.replace(compiled_name, display_name)
    return normalized


def _parse_ir_line(line_id: str, line: str) -> dict:
    comment: str | None = None
    body, separator, tail = line.partition(";")
    if separator:
        comment = tail.strip() or None
    body = body.strip()

    if not body:
        return {"id": line_id, "opcode": "", "operands": [], "comment": comment}

    if body.endswith(":"):
        return {"id": line_id, "opcode": body, "operands": [], "comment": comment}

    result: str | None = None
    opcode_text = body
    if " = " in body:
        result, opcode_text = [part.strip() for part in body.split(" = ", 1)]

    parts = opcode_text.split(None, 1)
    opcode = parts[0]
    operands = [item.strip() for item in parts[1].split(",")] if len(parts) > 1 else []
    return {"id": line_id, "opcode": opcode, "operands": operands, "result": result, "comment": comment}


def _strip_comment(line: str) -> str:
    return line.split("//", 1)[0]


def _extract_parenthesized(text: str) -> str:
    match = re.search(r"\((.*)\)", text)
    if not match:
        return ""
    return match.group(1).strip()


def _extract_call_name(line: str) -> str | None:
    match = CALL_RE.search(line)
    if not match:
        return None
    call_name = match.group(1)
    if call_name in CONTROL_KEYWORDS:
        return None
    return call_name


def _normalize_statement(line: str, prefix: str = "") -> str:
    statement = line.rstrip(";").strip()
    if prefix and statement.startswith(prefix):
        statement = statement[len(prefix) :].strip()
    statement = statement or prefix or "statement"
    return statement[:64]


def _string_or_empty(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _normalize_source_ranges(value: object, source_filename: str | None = None) -> list[dict]:
    if not isinstance(value, list):
        return []

    ranges: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            start_line = int(item["startLine"])
            start_column = int(item["startColumn"])
            end_line = int(item["endLine"])
            end_column = int(item["endColumn"])
        except (KeyError, TypeError, ValueError):
            continue

        file_name = _string_or_none(item.get("file"))
        if source_filename and not _source_file_matches(file_name, source_filename):
            continue

        source_range = {
            "file": file_name,
            "startLine": max(1, start_line),
            "startColumn": max(1, start_column),
            "endLine": max(1, end_line),
            "endColumn": max(1, end_column),
        }

        for string_key in ("rangeId", "astNodeId", "originNodeId", "generatedReason"):
            value_text = _string_or_none(item.get(string_key))
            if value_text is not None:
                source_range[string_key] = value_text

        for int_key in ("startOffset", "endOffset"):
            try:
                raw_value = item.get(int_key)
                if raw_value is not None:
                    source_range[int_key] = max(0, int(raw_value))
            except (TypeError, ValueError):
                pass

        if "generated" in item:
            source_range["generated"] = bool(item.get("generated"))

        ranges.append(source_range)

    return ranges


def _filter_asm_lines_to_source_sections(lines: list[dict]) -> list[dict]:
    sections: list[list[dict]] = []
    current_section: list[dict] = []

    for line in lines:
        if _is_global_asm_label(line):
            if current_section:
                sections.append(current_section)
            current_section = [line]
            continue
        if current_section:
            current_section.append(line)

    if current_section:
        sections.append(current_section)

    filtered: list[dict] = []
    for section in sections:
        if any(line.get("sourceRanges") for line in section):
            filtered.extend(section)

    if filtered:
        return filtered

    return [line for line in lines if line.get("sourceRanges")]


def _is_global_asm_label(line: dict) -> bool:
    label = _string_or_none(line.get("label"))
    if label:
        return not label.startswith(".")
    text = _string_or_empty(line.get("text")).strip()
    return bool(text.endswith(":") and not text.startswith("."))


def _source_file_matches(file_name: str | None, source_filename: str) -> bool:
    if not file_name:
        return False

    normalized = file_name.replace("\\", "/")
    basename = normalized.rsplit("/", 1)[-1]
    return basename == source_filename and "/src/std/" not in normalized
