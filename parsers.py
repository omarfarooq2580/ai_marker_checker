import ast
import json
import re

from config import TECH_MATRIX


def _record(bucket, tech_name, category, value, location):
    bucket.setdefault(tech_name, {})
    cat_map = bucket[tech_name].setdefault(category, {})
    cat_map.setdefault(value, set()).add(location)


def _resolve_overlaps(candidates):
    """candidates: list of (start, end, tech, category, value).
    Longest span wins; overlapping shorter spans are dropped."""
    candidates.sort(key=lambda c: (-(c[1] - c[0]), c[0]))
    accepted = []
    occupied = []

    def overlaps(a, b, c, d):
        return a < d and c < b

    for start, end, tech, category, value in candidates:
        if any(overlaps(start, end, o_s, o_e) for o_s, o_e in occupied):
            continue
        accepted.append((tech, category, value))
        occupied.append((start, end))
    return accepted


def scan_text_for_patterns(text, file_path, location_label, detections):
    """Regex-based non-overlapping scan across all pattern categories
    except import identifiers (handled separately for .py/.ipynb)."""
    candidates = []
    for entry in TECH_MATRIX:
        tech = entry["technology"]
        for category, plist in entry["patterns"].items():
            for raw_value, compiled in plist:
                try:
                    for m in re.finditer(compiled, text, re.IGNORECASE):
                        candidates.append((m.start(), m.end(), tech, category, raw_value))
                except re.error:
                    continue
    for tech, category, value in _resolve_overlaps(candidates):
        _record(detections, tech, category, value, location_label)


def _match_import_identifier(name):
    matches = []
    for entry in TECH_MATRIX:
        for ident in entry["import_identifiers"]:
            if ident == name or name.startswith(ident + ".") or ident in name:
                matches.append((entry["technology"], ident))
    return matches


def scan_python_ast(source, file_path, detections):
    """Returns True on success, False on SyntaxError (caller should
    fall back to plain regex scan)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    identifiers = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                identifiers.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod:
                identifiers.append((mod, node.lineno))
            for alias in node.names:
                full = f"{mod}.{alias.name}" if mod else alias.name
                identifiers.append((full, node.lineno))
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                identifiers.append((func.attr, node.lineno))
            elif isinstance(func, ast.Name):
                identifiers.append((func.id, node.lineno))

    seen = set()
    best_per_name_line = {}
    for name, lineno in identifiers:
        key = (name, lineno)
        if key in seen:
            continue
        seen.add(key)
        for tech, ident in _match_import_identifier(name):
            existing = best_per_name_line.get((tech, lineno))
            if existing is None or len(ident) > len(existing):
                best_per_name_line[(tech, lineno)] = ident

    for (tech, lineno), ident in best_per_name_line.items():
        _record(detections, tech, "imports", ident, f"line {lineno}")

    scan_text_for_patterns(source, file_path, "source", detections)
    return True


def parse_py(file_path, text, detections):
    ok = scan_python_ast(text, file_path, detections)
    if not ok:
        for lineno, line in enumerate(text.splitlines(), start=1):
            scan_text_for_patterns(line, file_path, f"line {lineno}", detections)


def parse_ipynb(file_path, text, detections):
    try:
        nb = json.loads(text)
    except json.JSONDecodeError:
        return
    for idx, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", [])
        code_text = "".join(src) if isinstance(src, list) else src
        ok = scan_python_ast(code_text, file_path, detections)
        if not ok:
            for lineno, line in enumerate(code_text.splitlines(), start=1):
                scan_text_for_patterns(line, file_path, f"cell {idx} line {lineno}", detections)


def _walk_json(value, path, file_path, detections):
    if isinstance(value, dict):
        for k, v in value.items():
            scan_text_for_patterns(str(k), file_path, f"key:{path}.{k}", detections)
            _walk_json(v, f"{path}.{k}", file_path, detections)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _walk_json(item, f"{path}[{i}]", file_path, detections)
    else:
        scan_text_for_patterns(str(value), file_path, f"value:{path}", detections)


def parse_json(file_path, text, detections):
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return
    _walk_json(data, "$", file_path, detections)


def parse_jsonl(file_path, text, detections):
    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            _walk_json(obj, f"line{lineno}", file_path, detections)
        except json.JSONDecodeError:
            scan_text_for_patterns(line, file_path, f"line {lineno}", detections)


def parse_plaintext(file_path, text, detections):
    for lineno, line in enumerate(text.splitlines(), start=1):
        scan_text_for_patterns(line, file_path, f"line {lineno}", detections)


PARSER_DISPATCH = {
    ".py": parse_py,
    ".ipynb": parse_ipynb,
    ".json": parse_json,
    ".jsonl": parse_jsonl,
    ".env": parse_plaintext,
    ".yaml": parse_plaintext,
    ".yml": parse_plaintext,
    ".txt": parse_plaintext,
}
