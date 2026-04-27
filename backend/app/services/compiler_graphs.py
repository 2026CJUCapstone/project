from __future__ import annotations

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
