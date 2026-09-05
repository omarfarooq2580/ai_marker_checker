"""
AI/ML Marker Scanner — Web Dashboard
FastAPI backend wiring the existing scanning pipeline (config.py, parsers.py,
reader.py) into a JSON API + Jinja2 dashboard.

Run with:
    pip install fastapi uvicorn jinja2 python-multipart --break-system-packages
    uvicorn app:app --reload --port 8000
"""

import json
import os
import time
import traceback
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from config import TARGET_EXTENSIONS, EXCLUDE_DIRS, OUTPUT_JSON, SIGNAL_LABELS
from parsers import parse_target
from reader import fetch_repo_files, GitHubFetchError

app1 = FastAPI(title="AI/ML Marker Scanner")
templates = Jinja2Templates(directory="templates")

# Holds the most recently generated catalog so /api/export-json can serve it
# without forcing a re-scan. Simple in-process cache — fine for a single-user
# / demo deployment; swap for a real store (redis, db) for multi-worker prod.
_LAST_RUN = {"catalog": None, "generated_at": None}


# --------------------------------------------------------------------------
# Scanning helpers (request-scoped; each call gets its own `detections` dict
# so concurrent requests never share mutable state)
# --------------------------------------------------------------------------

def read_text(file_path: Path) -> Optional[str]:
    try:
        with open(file_path, "r", encoding="utf-8", errors="strict") as f:
            return f.read()
    except UnicodeDecodeError:
        try:
            with open(file_path, "r", encoding="latin-1") as f:
                return f.read()
        except OSError:
            return None
    except (FileNotFoundError, OSError):
        return None


def collect_local_files(target_path: str):
    target = Path(target_path)
    files = []
    errors = []
    if target.is_file():
        if target.suffix.lower() in TARGET_EXTENSIONS:
            files.append(target)
        else:
            errors.append(f"Skipping unsupported extension: {target}")
    elif target.is_dir():
        for root, dirs, filenames in os.walk(target):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for fname in filenames:
                fpath = Path(root) / fname
                if fpath.suffix.lower() in TARGET_EXTENSIONS:
                    files.append(fpath)
    else:
        errors.append(f"Target not found: {target_path}")
    return files, errors


def scan_local_targets(files, detections):
    scanned_labels = []
    for fpath in files:
        text = read_text(fpath)
        if text is None:
            continue
        label = str(fpath)
        parse_target(label, text, detections)
        scanned_labels.append(label)
    return scanned_labels


def scan_in_memory_targets(pairs, detections):
    scanned_labels = []
    for label, text in pairs:
        parse_target(label, text, detections)
        scanned_labels.append(label)
    return scanned_labels


def build_catalog(detections):
    catalog = []
    for tech, data in detections.items():
        categories = data["categories"]
        signals = {}
        for category in (
            "packages", "imports", "environment_variables", "endpoints",
            "code_patterns", "docker_images", "models", "extensions_and_metrics",
        ):
            signals[category] = sorted(categories.get(category, set()))

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

    # Sort by most evidence first — busiest / most-confident detections lead
    catalog.sort(key=lambda entry: len(entry["evidence"]), reverse=True)
    return catalog


def compute_metrics(catalog, files_scanned):
    evidence_matches = sum(len(entry["evidence"]) for entry in catalog)
    return {
        "files_scanned": files_scanned,
        "technologies_detected": len(catalog),
        "evidence_matches": evidence_matches,
    }


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

@app1.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app1.post("/api/scan")
async def api_scan(
    target_type: str = Form(...),        # "local" | "github"
    target_path: str = Form(...),
    github_token: str = Form(""),
    execution_mode: str = Form("in-memory"),  # "in-memory" | "file"
):
    detections = {}
    scanned_labels = []
    warnings = []
    start = time.time()

    try:
        if target_type == "local":
            files, errors = collect_local_files(target_path.strip())
            warnings.extend(errors)
            if not files:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "No scannable files found under that path."},
                )
            scanned_labels = scan_local_targets(files, detections)

        elif target_type == "github":
            token = github_token.strip() or None
            mode = execution_mode if execution_mode in ("in-memory", "file") else "in-memory"
            try:
                result = fetch_repo_files(target_path.strip(), mode=mode, github_token=token)
            except GitHubFetchError as e:
                return JSONResponse(status_code=400, content={"success": False, "error": str(e)})

            if not result:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "No scannable files retrieved from repository."},
                )

            if mode == "in-memory":
                scanned_labels = scan_in_memory_targets(result, detections)
            else:
                scanned_labels = scan_local_targets(result, detections)

        else:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"Unknown target_type '{target_type}'."},
            )

        catalog = build_catalog(detections)
        metrics = compute_metrics(catalog, len(scanned_labels))
        elapsed = round(time.time() - start, 3)

        _LAST_RUN["catalog"] = catalog
        _LAST_RUN["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

        return JSONResponse(content={
            "success": True,
            "metrics": metrics,
            "elapsed_seconds": elapsed,
            "scanned_labels": scanned_labels,
            "catalog": catalog,
            "warnings": warnings,
        })

    except Exception as e:  # noqa: BLE001 — surface unexpected errors to the UI instead of a bare 500
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"success": False, "error": f"Unexpected server error: {e}"})


@app1.get("/api/export-json")
async def export_json():
    catalog = _LAST_RUN["catalog"]
    if catalog is None:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "No scan results available yet. Run a scan first."},
        )
    payload = json.dumps(catalog, indent=2)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{OUTPUT_JSON}"'},
    )


@app1.get("/api/health")
async def health():
    return {"status": "ok", "service": "AI/ML Marker Scanner"}