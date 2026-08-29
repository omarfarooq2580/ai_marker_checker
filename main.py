import json
import os
import sys
from pathlib import Path

from config import SKIP_DIRS, PARSER_EXTENSIONS, OUTPUT_JSON
from parsers import PARSER_DISPATCH

TARGET_PATH = r"C:\Users\omarm\Downloads\rag_chain.py"

detections = {}  # tech -> category -> value -> set(locations)


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


def scan_file(file_path):
    suffix = file_path.suffix.lower()
    handler = PARSER_DISPATCH.get(suffix)
    if handler is None:
        return
    text = read_text(file_path)
    if text is None:
        return
    try:
        handler(file_path, text, detections)
    except json.JSONDecodeError as e:
        print(f"[!] JSONDecodeError in {file_path}: {e}")
    except UnicodeDecodeError as e:
        print(f"[!] UnicodeDecodeError in {file_path}: {e}")
    except Exception as e:
        print(f"[!] Unexpected error scanning {file_path}: {e}")


def collect_files(target_path):
    target = Path(target_path)
    files = []
    if target.is_file():
        if target.suffix.lower() in PARSER_EXTENSIONS:
            files.append(target)
    elif target.is_dir():
        for root, dirs, filenames in os.walk(target):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fname in filenames:
                fpath = Path(root) / fname
                if fpath.suffix.lower() in PARSER_EXTENSIONS:
                    files.append(fpath)
    else:
        print(f"[!] Target not found: {target_path}")
    return files


def build_catalog():
    catalog = []
    for tech, categories in detections.items():
        signals = {}
        for category in (
            "packages", "imports", "environment_variables", "endpoints",
            "code_patterns", "docker_images", "models", "extensions_and_metrics",
        ):
            values = sorted(categories.get(category, {}).keys())
            signals[category] = values
        catalog.append({"technology": tech, "signals": signals})
    return catalog


def print_report(files_scanned):
    print("=" * 60)
    print(f"Scan target: {TARGET_PATH}")
    print(f"Files scanned: {len(files_scanned)}")
    print("=" * 60)
    total = 0
    for tech, categories in detections.items():
        print(f"\n[Technology] {tech}")
        for category, values in categories.items():
            for value, locations in values.items():
                total += len(locations)
                loc_str = ", ".join(sorted(locations))
                print(f"  [{category}] '{value}' -> {loc_str}")
    print("\n" + "=" * 60)
    print(f"AI/ML Markers Detected: {'YES' if detections else 'NO'}")
    print(f"Total Signal Occurrences: {total}")
    print(f"Distinct Technologies: {len(detections)}")
    print("=" * 60)


def main():
    files = collect_files(TARGET_PATH)
    if not files:
        print("[!] No scannable files found.")
        sys.exit(1)

    for f in files:
        scan_file(f)

    print_report(files)

    catalog = build_catalog()
    try:
        with open(OUTPUT_JSON, "w", encoding="utf-8") as out:
            json.dump(catalog, out, indent=2)
        print(f"\n[+] Catalog written to {OUTPUT_JSON}")
    except OSError as e:
        print(f"[!] Failed to write {OUTPUT_JSON}: {e}")


if __name__ == "__main__":
    main()