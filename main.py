import json
import os
import sys
from pathlib import Path

from config import TARGET_EXTENSIONS, EXCLUDE_DIRS, OUTPUT_JSON
from parsers import parse_target
from reader import fetch_repo_files, GitHubFetchError

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


def collect_local_files(target_path):
    target = Path(target_path)
    files = []
    if target.is_file():
        if target.suffix.lower() in TARGET_EXTENSIONS:
            files.append(target)
        else:
            print(f"[!] Skipping unsupported extension: {target}")
    elif target.is_dir():
        for root, dirs, filenames in os.walk(target):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for fname in filenames:
                fpath = Path(root) / fname
                if fpath.suffix.lower() in TARGET_EXTENSIONS:
                    files.append(fpath)
    else:
        print(f"[!] Target not found: {target_path}")
    return files


def scan_local_targets(files):
    scanned_labels = []
    for fpath in files:
        text = read_text(fpath)
        if text is None:
            continue
        label = str(fpath)
        parse_target(label, text, detections)
        scanned_labels.append(label)
    return scanned_labels


def scan_in_memory_targets(pairs):
    """pairs: list of (virtual_path_str, text_content)"""
    scanned_labels = []
    for label, text in pairs:
        parse_target(label, text, detections)
        scanned_labels.append(label)
    return scanned_labels


def build_catalog():
    """Builds the ai_detection_catalog.json deliverable. Each technology
    entry keeps the aggregated 'signals' block (unique marker values per
    category) and adds an 'evidence' list — one record per distinct
    (signal, file, evidence) occurrence — carrying the exact file and
    matched snippet that proves usage, e.g.:
        {"technology": "OpenAI", "signal": "package_dependency",
         "file": "requirements.txt", "evidence": "openai==2.x"}
    """
    catalog = []
    for tech, data in detections.items():
        categories = data["categories"]
        signals = {}
        for category in (
            "packages", "imports", "environment_variables", "endpoints",
            "code_patterns", "docker_images", "models", "extensions_and_metrics",
        ):
            values = sorted(categories.get(category, set()))
            signals[category] = values

        evidence = [
            {
                "technology": tech,
                "signal": signal_label,
                "file": file_label,
                "evidence": evidence_text,
            }
            for signal_label, file_label, evidence_text in sorted(data["occurrences"])
        ]

        catalog.append({
            "technology": tech,
            "signals": signals,
            "evidence": evidence,
        })
    return catalog


def print_report(scanned_labels):
    print("\n" + "=" * 60)
    print(f"Files/targets scanned: {len(scanned_labels)}")
    print("=" * 60)
    total_occurrences = 0
    for tech, data in detections.items():
        print(f"\n[Technology] {tech}")
        for signal_label, file_label, evidence_text in sorted(data["occurrences"]):
            total_occurrences += 1
            print(f"  [{signal_label}] {file_label} -> {evidence_text}")
    print("\n" + "=" * 60)
    print(f"AI/ML Markers Detected: {'YES' if detections else 'NO'}")
    print(f"Total Evidence Occurrences: {total_occurrences}")
    print(f"Distinct Technologies: {len(detections)}")
    print("=" * 60)


def export_catalog():
    catalog = build_catalog()
    try:
        with open(OUTPUT_JSON, "w", encoding="utf-8") as out:
            json.dump(catalog, out, indent=2)
        print(f"\n[+] Catalog written to {OUTPUT_JSON}")
    except OSError as e:
        print(f"[!] Failed to write {OUTPUT_JSON}: {e}")


def prompt_local():
    path_str = input("Enter local file or folder path: ").strip()
    if not path_str:
        print("[!] No path provided.")
        return
    files = collect_local_files(path_str)
    if not files:
        print("[!] No scannable files found under that path.")
        return
    print(f"[*] Scanning {len(files)} file(s)...")
    scanned = scan_local_targets(files)
    print_report(scanned)
    export_catalog()


def prompt_github():
    repo_url = input("Enter GitHub repo URL (e.g. https://github.com/owner/repo): ").strip()
    if not repo_url:
        print("[!] No URL provided.")
        return
    mode = input("Execution mode ['in-memory' / 'file']: ").strip().lower()
    if mode not in ("in-memory", "file"):
        print(f"[!] Unrecognized mode '{mode}', defaulting to 'in-memory'.")
        mode = "in-memory"

    token = input("Enter GitHub Access Token (press Enter to skip): ").strip() or None

    try:
        result = fetch_repo_files(repo_url, mode=mode, github_token=token)
    except GitHubFetchError as e:
        print(f"[!] GitHub fetch failed: {e}")
        return

    if not result:
        print("[!] No scannable files retrieved from repository.")
        return

    if mode == "in-memory":
        print(f"[*] Scanning {len(result)} file(s) in memory...")
        scanned = scan_in_memory_targets(result)
    else:
        print(f"[*] Scanning {len(result)} extracted file(s) on disk...")
        scanned = scan_local_targets(result)

    print_report(scanned)
    export_catalog()


def main():
    print("AI/ML Marker Scanner")
    print("[1] Scan Local File or Folder")
    print("[2] Scan Remote GitHub Repository URL")
    choice = input("Select an option: ").strip()

    if choice == "1":
        prompt_local()
    elif choice == "2":
        prompt_github()
    else:
        print("[!] Invalid selection. Exiting.")
        sys.exit(1)


if __name__ == "__main__":
    main()