import ast
import json
import re
from pathlib import Path

from config import TECH_MATRIX, SIGNAL_LABELS


def _record(bucket, tech_name, category, marker_value, file_label, evidence_text):
    entry = bucket.setdefault(tech_name, {"categories": {}, "occurrences": set()})
    entry["categories"].setdefault(category, set()).add(marker_value)
    entry["occurrences"].add((
        SIGNAL_LABELS.get(category, category),
        file_label,
        evidence_text.strip(),
    ))


def _resolve_overlaps(candidates):
    """candidates: list of (start, end, tech, category, value).
    Longest span wins; overlapping shorter spans are dropped so a
    marker fully contained in a longer match isn't double-counted."""
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


def scan_text_for_patterns(text, file_label, detections):
    """Regex-based non-overlapping scan across all pattern categories
    (packages, env vars, endpoints, code patterns, docker images,
    models, extensions/metrics). Language-agnostic. `text` is treated
    as the evidence snippet (e.g. one source line, one config line, or
    a 'key: value' pair) and is stored verbatim in the evidence record."""
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
        _record(detections, tech, category, value, file_label, text)


def _match_import_identifier(name):
    matches = []
    for entry in TECH_MATRIX:
        for ident in entry["import_identifiers"]:
            if ident == name or name.startswith(ident + ".") or ident in name:
                matches.append((entry["technology"], ident))
    return matches


def parse_python(file_label, text, detections):
    """AST-based import/call extraction; falls back to plain regex
    scan on SyntaxError. Scans line-by-line (rather than the whole
    source at once) so each detection carries a concrete evidence
    line, at the cost of missing patterns that span multiple lines."""
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        print(f"[!] SyntaxError in {file_label}: {e}. Falling back to regex scan.")
        for line in text.splitlines():
            scan_text_for_patterns(line, file_label, detections)
        return

    source_lines = text.splitlines()
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
        line_text = source_lines[lineno - 1] if 0 < lineno <= len(source_lines) else ident
        _record(detections, tech, "imports", ident, file_label, line_text)

    for line in source_lines:
        scan_text_for_patterns(line, file_label, detections)


def parse_js_ts(file_label, text, detections):
    """Regex-only scan for JS/TS: import/require statements, endpoints,
    env var references, SDK instantiation patterns."""
    for line in text.splitlines():
        scan_text_for_patterns(line, file_label, detections)


def parse_text_config(file_label, text, detections):
    """YAML / TOML: line-by-line regex scan (values, keys, endpoints)."""
    for line in text.splitlines():
        scan_text_for_patterns(line, file_label, detections)


def _walk_json(value, path, file_label, detections):
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                _walk_json(v, f"{path}.{k}", file_label, detections)
            else:
                scan_text_for_patterns(f"{k}: {v}", file_label, detections)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _walk_json(item, f"{path}[{i}]", file_label, detections)
    else:
        scan_text_for_patterns(str(value), file_label, detections)


def parse_json_config(file_label, text, detections):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[!] JSONDecodeError in {file_label}: {e}. Falling back to regex scan.")
        for line in text.splitlines():
            scan_text_for_patterns(line, file_label, detections)
        return
    _walk_json(data, "$", file_label, detections)


PARSER_DISPATCH = {
    ".py": parse_python,
    ".js": parse_js_ts,
    ".ts": parse_js_ts,
    ".yaml": parse_text_config,
    ".yml": parse_text_config,
    ".toml": parse_text_config,
    ".txt": parse_text_config,  # e.g. requirements.txt dependency pins
    ".json": parse_json_config,
}


def parse_target(label, text, detections):
    """label: file path or virtual path string; used both to pick the
    parser (via its suffix) and as the 'file' field in evidence records."""
    suffix = Path(label).suffix.lower()
    handler = PARSER_DISPATCH.get(suffix)
    if handler is None:
        return
    try:
        handler(label, text, detections)
    except Exception as e:
        print(f"[!] Unexpected error parsing {label}: {e}")