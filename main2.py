import ast
import json
import os
import re
import sys
from pathlib import Path

TARGET_PATH = r"C:\Users\omarm\Downloads\rag_chain.py"

SKIP_DIRS = {".git", "__pycache__", ".venv"}

FRAMEWORK_MARKERS = {
    "OpenAI": ["openai"],
    "Azure OpenAI": ["azure-openai", "AzureOpenAI", "azure_endpoint", "AZURE_OPENAI_KEY"],
    "Anthropic": ["anthropic"],
    "Gemini": ["google.generativeai", "google-genai", "GenerativeModel"],
    "Mistral": ["mistralai", "MistralClient"],
    "Cohere": ["cohere"],
    "Hugging Face": ["transformers", "huggingface_hub", "AutoModelForCausalLM", "pipeline"],
    "Ollama": ["ollama", "OLLAMA_HOST"],
    "vLLM": ["vllm", "SamplingParams"],
    "PyTorch": ["torch", "nn.Module"],
    "TensorFlow": ["tensorflow", "tf.keras"],
    "ONNX": ["onnx", "onnxruntime"],
    "LangChain": ["langchain", "langchain_core", "langchain_community"],
    "LlamaIndex": ["llama_index", "VectorStoreIndex"],
    "CrewAI": ["crewai"],
    "AutoGen": ["autogen", "pyautogen", "ConversableAgent"],
    "Semantic Kernel": ["semantic_kernel"],
    "Vector DBs": ["chromadb", "pinecone", "qdrant_client", "qdrant", "weaviate", "pymilvus", "milvus", "faiss"],
}

KEY_PATTERNS = [
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
    "MISTRAL_API_KEY", "COHERE_API_KEY", "HF_TOKEN", "AZURE_OPENAI_KEY",
]

MODEL_ID_PATTERNS = [
    "gpt-4o", "gpt-4", "gpt-3.5", "claude-3-5-sonnet", "claude-3",
    "gemini-1.5", "mistral-7b", "llama-3", "text-embedding-3",
    "text-embedding", "whisper",
]

ALL_MARKERS = []
for _cat, _markers in FRAMEWORK_MARKERS.items():
    for _m in _markers:
        ALL_MARKERS.append((_cat, _m))
for _m in KEY_PATTERNS:
    ALL_MARKERS.append(("API Key Pattern", _m))
for _m in MODEL_ID_PATTERNS:
    ALL_MARKERS.append(("Model ID", _m))

# Longest marker first so containment resolution prefers the more specific match
ALL_MARKERS.sort(key=lambda pair: len(pair[1]), reverse=True)

detections = set()  # dedupe via set of (category, file_path, line_or_key, marker)


def add_detection(category, file_path, line_or_key, marker):
    detections.add((category, str(file_path), str(line_or_key), marker))


def find_nonoverlapping_matches(text):
    """
    Find all marker matches in text, resolve overlaps so a shorter marker
    that is fully contained inside a longer/already-accepted match is
    dropped (prevents double-counting e.g. 'gpt-4' inside 'gpt-4o',
    'openai' inside 'azure-openai', 'text-embedding' inside 'text-embedding-3').
    """
    candidates = []
    for category, marker in ALL_MARKERS:
        pattern = r'\b' + re.escape(marker) + r'\b'
        for m in re.finditer(pattern, text, re.IGNORECASE):
            candidates.append((m.start(), m.end(), category, marker))

    # Longest span first, then earliest start
    candidates.sort(key=lambda c: (-(c[1] - c[0]), c[0]))

    accepted = []
    occupied = []  # list of (start, end) already accepted spans

    def overlaps(a_start, a_end, b_start, b_end):
        return a_start < b_end and b_start < a_end

    for start, end, category, marker in candidates:
        if any(overlaps(start, end, os_, oe_) for os_, oe_ in occupied):
            continue
        accepted.append((category, marker))
        occupied.append((start, end))

    return accepted


def scan_text_lines(lines, file_path):
    for lineno, line in enumerate(lines, start=1):
        for category, marker in find_nonoverlapping_matches(line):
            add_detection(category, file_path, lineno, marker)


def read_text(file_path):
    try:
        with open(file_path, "r", encoding="utf-8", errors="strict") as f:
            return f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, "r", encoding="latin-1") as f:
                return f.read()
        except OSError as e:
            print(f"[!] Unicode/read error on {file_path}: {e}")
            return None
    except FileNotFoundError:
        print(f"[!] File not found: {file_path}")
        return None
    except OSError as e:
        print(f"[!] OS error reading {file_path}: {e}")
        return None


def ast_scan_py(source, file_path):
    identifiers = []  # (name, lineno) collected once per node, deduped per node
    try:
        tree = ast.parse(source)
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

        # Dedupe identical (name, lineno) pairs before matching to avoid
        # counting the same identifier twice (e.g. import + call on one line)
        seen_pairs = set()
        for name, lineno in identifiers:
            key = (name, lineno)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            for category, marker in find_nonoverlapping_matches(name):
                add_detection(category, file_path, lineno, marker)
        return True
    except SyntaxError as e:
        print(f"[!] SyntaxError in {file_path}: {e}. Falling back to regex scan.")
        return False


def scan_py(file_path):
    source = read_text(file_path)
    if source is None:
        return
    ok = ast_scan_py(source, file_path)
    if not ok:
        scan_text_lines(source.splitlines(), file_path)


def scan_ipynb(file_path):
    raw = read_text(file_path)
    if raw is None:
        return
    try:
        nb = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[!] JSONDecodeError in {file_path}: {e}")
        return
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", [])
        if isinstance(src, list):
            code_lines = [line.rstrip("\n") for line in src]
        else:
            code_lines = src.splitlines()
        code_text = "\n".join(code_lines)
        ok = ast_scan_py(code_text, file_path)
        if not ok:
            scan_text_lines(code_lines, file_path)


def scan_json_value(key, value, file_path, path_prefix=""):
    full_key = f"{path_prefix}.{key}" if path_prefix else str(key)
    if isinstance(value, dict):
        for k, v in value.items():
            scan_json_value(k, v, file_path, full_key)
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            scan_json_value(f"{key}[{idx}]", item, file_path, path_prefix)
    else:
        # Scan key and value separately (not concatenated) to avoid a
        # marker spanning/matching across the artificial join boundary
        for category, marker in find_nonoverlapping_matches(str(key)):
            add_detection(category, file_path, full_key, marker)
        for category, marker in find_nonoverlapping_matches(str(value)):
            add_detection(category, file_path, full_key, marker)


def scan_json(file_path):
    raw = read_text(file_path)
    if raw is None:
        return
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            for k, v in data.items():
                scan_json_value(k, v, file_path)
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                scan_json_value(f"[{idx}]", item, file_path)
    except json.JSONDecodeError as e:
        print(f"[!] JSONDecodeError in {file_path}: {e}")


def scan_jsonl(file_path):
    raw = read_text(file_path)
    if raw is None:
        return
    for lineno, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                for k, v in obj.items():
                    scan_json_value(k, v, file_path, f"line{lineno}")
            else:
                scan_text_lines([line], file_path)
        except json.JSONDecodeError:
            scan_text_lines([line], file_path)


def scan_plaintext(file_path):
    raw = read_text(file_path)
    if raw is None:
        return
    scan_text_lines(raw.splitlines(), file_path)


PARSER_MAP = {
    ".py": scan_py,
    ".ipynb": scan_ipynb,
    ".json": scan_json,
    ".jsonl": scan_jsonl,
    ".env": scan_plaintext,
    ".yaml": scan_plaintext,
    ".yml": scan_plaintext,
    ".txt": scan_plaintext,
}


def scan_file(file_path):
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()
    parser = PARSER_MAP.get(suffix)
    if parser is None:
        return False
    try:
        parser(file_path)
        return True
    except FileNotFoundError:
        print(f"[!] File not found: {file_path}")
    except UnicodeDecodeError as e:
        print(f"[!] UnicodeDecodeError in {file_path}: {e}")
    except json.JSONDecodeError as e:
        print(f"[!] JSONDecodeError in {file_path}: {e}")
    except Exception as e:
        print(f"[!] Unexpected error scanning {file_path}: {e}")
    return False


def collect_files(target_path):
    target_path = Path(target_path)
    files = []
    if target_path.is_file():
        files.append(target_path)
    elif target_path.is_dir():
        for root, dirs, filenames in os.walk(target_path):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fname in filenames:
                fpath = Path(root) / fname
                if fpath.suffix.lower() in PARSER_MAP:
                    files.append(fpath)
    else:
        print(f"[!] Target not found: {target_path}")
    return files


def print_report(files_scanned):
    print("=" * 60)
    print(f"Scan target: {TARGET_PATH}")
    print(f"Files scanned: {len(files_scanned)}")
    print("=" * 60)

    by_file = {}
    for category, fpath, loc, marker in detections:
        by_file.setdefault(fpath, []).append((category, loc, marker))

    for fpath in files_scanned:
        fpath_str = str(fpath)
        print(f"\n[File] {fpath_str}")
        file_dets = by_file.get(fpath_str, [])
        if not file_dets:
            print("  (no markers detected)")
            continue
        by_category = {}
        for category, loc, marker in file_dets:
            by_category.setdefault(category, []).append((loc, marker))
        for category, entries in by_category.items():
            print(f"  [Category] {category}")
            for loc, marker in sorted(entries, key=lambda e: str(e[0])):
                print(f"    - Marker: '{marker}' | Location: {loc}")

    total_count = len(detections)
    detected_any = total_count > 0
    print("\n" + "=" * 60)
    print(f"AI/ML Markers Detected: {'YES' if detected_any else 'NO'}")
    print(f"Total Unique Marker Count: {total_count}")
    print("=" * 60)


def main():
    files = collect_files(TARGET_PATH)
    if not files:
        print("[!] No scannable files found.")
        sys.exit(1)
    for f in files:
        scan_file(f)
    print_report(files)


if __name__ == "__main__":
    main()