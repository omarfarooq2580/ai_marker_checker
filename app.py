"""
AI/ML Marker Scanner — Web Dashboard
FastAPI backend wiring the scanning pipeline into a JSON API + Jinja2 dashboard + CrewAI integration.
"""

import json
import os
import time
import traceback
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from config import TARGET_EXTENSIONS, EXCLUDE_DIRS, OUTPUT_JSON, SIGNAL_LABELS
from parsers import parse_target
from reader import fetch_repo_files, GitHubFetchError
import crew_analyzer

app1 = FastAPI(title="AI/ML Marker Scanner")
templates = Jinja2Templates(directory="templates")

_LAST_RUN = {"catalog": None, "generated_at": None, "repo_name": "local-scan"}

# --- PERSISTENT LOCAL STORAGE SETUP ---
DB_FILE = Path("scans_db.json")
BATCH_FILE = Path("batch_targets.json")


def load_scans_db() -> dict:
    if DB_FILE.exists():
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    else:
        save_scans_db({})
        return {}


def save_scans_db(db: dict) -> None:
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)


# Load existing scan records on application startup
SCANS_DB = load_scans_db()


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

    catalog.sort(key=lambda entry: len(entry["evidence"]), reverse=True)
    return catalog


def compute_metrics(catalog, files_scanned):
    evidence_matches = sum(len(entry["evidence"]) for entry in catalog)
    return {
        "files_scanned": files_scanned,
        "technologies_detected": len(catalog),
        "evidence_matches": evidence_matches,
    }


def _get_all_assets_from_catalog(catalog):
    assets = []
    if not catalog:
        return assets
    for idx, entry in enumerate(catalog, start=1):
        assets.append({
            "asset_id": f"asset_{idx:03d}",
            "repository_name": entry.get("repository_name", "Unknown Repo"),
            "technology": entry.get("technology"),
            "signals": entry.get("signals", {}),
            "evidence_count": len(entry.get("evidence", []))
        })
    return assets


def generate_sequential_scan_id() -> str:
    """Generates an incremental, sequential scan ID (e.g., scan_001, scan_002)."""
    next_number = len(SCANS_DB) + 1
    return f"scan_{next_number:03d}"


def execute_single_scan(target: dict, mode: str = "in-memory"):
    """Internal helper executing scanning logic for one repository target."""
    path = target.get("target_path", "").strip()
    type_target = target.get("target_type", "local")
    token = target.get("github_token", "").strip() or None

    if not path:
        return {"success": False, "error": "Target path/URL is empty."}

    start = time.time()
    detections = {}
    warnings = []

    try:
        if type_target == "local":
            files, errors = collect_local_files(path)
            warnings.extend(errors)
            if not files:
                return {"success": False, "error": f"No scannable files found at path: {path}"}
            scanned_labels = scan_local_targets(files, detections)
            repo_name = Path(path).name or "local-scan"

        elif type_target == "github":
            try:
                result = fetch_repo_files(path, mode=mode, github_token=token)
            except GitHubFetchError as e:
                return {"success": False, "error": str(e)}

            if not result:
                return {"success": False, "error": f"No scannable files retrieved from repository: {path}"}

            if mode == "in-memory":
                scanned_labels = scan_in_memory_targets(result, detections)
            else:
                scanned_labels = scan_local_targets(result, detections)

            repo_name = path.split("/")[-1].replace(".git", "") or "github-repo"
        else:
            return {"success": False, "error": f"Unknown target_type '{type_target}'."}

        catalog = build_catalog(detections)
        
        # Tag entries with repository name
        for entry in catalog:
            entry["repository_name"] = repo_name

        metrics = compute_metrics(catalog, len(scanned_labels))
        elapsed = round(time.time() - start, 3)

        scan_id = generate_sequential_scan_id()
        scan_record = {
            "scan_id": scan_id,
            "status": "completed",
            "ai_detected": len(catalog) > 0,
            "systems_found": len(catalog),
            "catalog": catalog,
            "repository_path": path,
            "repository_name": repo_name
        }

        # Persist scan to DB
        SCANS_DB[scan_id] = scan_record

        return {
            "success": True,
            "scan_id": scan_id,
            "status": scan_record["status"],
            "ai_detected": scan_record["ai_detected"],
            "systems_found": scan_record["systems_found"],
            "metrics": metrics,
            "elapsed_seconds": elapsed,
            "scanned_labels": scanned_labels,
            "catalog": catalog,
            "warnings": warnings,
            "repository_path": path,
            "repository_name": repo_name,
        }

    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": f"Unexpected error scanning {path}: {str(e)}"}


# --- API ENDPOINTS ---

@app1.post("/scan")
async def scan_repository(request: Request):
    """
    Accepts incoming targets JSON array, writes it to batch_targets.json, 
    and sequentially scans each repository, tagging entries with repository information.
    """
    try:
        targets: List[Dict[str, Any]] = await request.json()
        if not isinstance(targets, list) or len(targets) == 0:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "Request body must be a non-empty array of target objects."}
            )
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": f"Invalid JSON payload: {str(e)}"}
        )

    # 1. Update batch_targets.json on disk with submitted configuration
    try:
        with open(BATCH_FILE, "w", encoding="utf-8") as f:
            json.dump(targets, f, indent=2)
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Failed to update batch_targets.json: {str(e)}"}
        )

    # 2. Sequentially scan each repository and collect tagged catalog entries
    batch_results = []
    combined_catalog = []
    total_files_scanned = 0

    for target in targets:
        result = execute_single_scan(target)
        batch_results.append(result)
        if result.get("success"):
            combined_catalog.extend(result.get("catalog", []))
            total_files_scanned += result.get("metrics", {}).get("files_scanned", 0)

    # 3. Persist new scan records to disk
    save_scans_db(SCANS_DB)

    successful_results = [r for r in batch_results if r["success"]]

    if not successful_results:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error": "All repository scans failed.",
                "batch_results": batch_results,
            }
        )

    # Update global state with aggregated results across all scanned repos
    _LAST_RUN["catalog"] = combined_catalog
    _LAST_RUN["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _LAST_RUN["repo_name"] = "batch-scan"

    combined_metrics = compute_metrics(combined_catalog, total_files_scanned)

    return JSONResponse(content={
        "success": True,
        "total_scanned": len(batch_results),
        "scan_id": successful_results[-1]["scan_id"],
        "status": "completed",
        "ai_detected": len(combined_catalog) > 0,
        "systems_found": len(combined_catalog),
        "metrics": combined_metrics,
        "catalog": combined_catalog,
        "batch_results": batch_results,
    })


@app1.get("/scans")
async def list_scans():
    results = [
        {
            "scan_id": record["scan_id"],
            "status": record["status"],
            "ai_detected": record["ai_detected"],
            "systems_found": record["systems_found"],
            "repository_path": record["repository_path"]
        }
        for record in SCANS_DB.values()
    ]
    return JSONResponse(content={"scans": results})


@app1.get("/scans/{scan_id}")
async def get_scan_details(scan_id: str):
    record = SCANS_DB.get(scan_id)
    if not record:
        raise HTTPException(status_code=404, detail="Scan record not found")

    _LAST_RUN["catalog"] = record.get("catalog", [])
    _LAST_RUN["generated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _LAST_RUN["repo_name"] = Path(record.get("repository_path", "historical-scan")).name

    metrics = compute_metrics(_LAST_RUN["catalog"], len(_LAST_RUN["catalog"]))

    return JSONResponse(content={
        "success": True,
        "scan_id": record["scan_id"],
        "status": record["status"],
        "repository_path": record["repository_path"],
        "catalog": record.get("catalog", []),
        "metrics": metrics
    })


@app1.get("/assets")
async def list_assets():
    catalog = _LAST_RUN.get("catalog") or []
    assets = _get_all_assets_from_catalog(catalog)
    return JSONResponse(content={"assets": assets, "total": len(assets)})


@app1.get("/assets/{asset_id}")
async def get_asset(asset_id: str):
    catalog = _LAST_RUN.get("catalog") or []
    assets = _get_all_assets_from_catalog(catalog)
    for asset in assets:
        if asset["asset_id"] == asset_id:
            return JSONResponse(content=asset)
    raise HTTPException(status_code=404, detail="Asset not found")


@app1.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app1.post("/api/analyze-crew")
async def analyze_crew():
    catalog_data = _LAST_RUN.get("catalog")
    repo_name = _LAST_RUN.get("repo_name", "scanned-repo")

    if catalog_data is None:
        raise HTTPException(
            status_code=400,
            detail="No scan results available yet. Run a repository scan first."
        )

    try:
        analysis_result = await crew_analyzer.run_crew_analysis(catalog_data, repository_name=repo_name)
        return JSONResponse(content={"success": True, "data": analysis_result})
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"CrewAI execution error: {str(e)}")

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