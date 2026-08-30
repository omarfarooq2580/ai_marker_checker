import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from config import TARGET_EXTENSIONS, EXCLUDE_DIRS, GITHUB_API_ROOT


class GitHubFetchError(Exception):
    pass


def _parse_repo_url(repo_url):
    m = re.search(r"github\.com[/:]([^/]+)/([^/#?]+)", repo_url.strip())
    if not m:
        raise GitHubFetchError(f"Could not parse owner/repo from URL: {repo_url}")
    owner, repo = m.group(1), m.group(2)
    repo = repo[:-4] if repo.endswith(".git") else repo
    return owner, repo


def _api_get(url):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-marker-scanner",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise GitHubFetchError(f"GitHub API HTTP error {e.code} for {url}: {e.reason}")
    except urllib.error.URLError as e:
        raise GitHubFetchError(f"GitHub API connection error for {url}: {e.reason}")
    except json.JSONDecodeError as e:
        raise GitHubFetchError(f"GitHub API returned invalid JSON for {url}: {e}")


def _is_excluded_path(path_str):
    parts = Path(path_str).parts
    return any(part in EXCLUDE_DIRS for part in parts)


def _is_target_extension(path_str):
    return Path(path_str).suffix.lower() in TARGET_EXTENSIONS


def _get_default_branch(owner, repo):
    info = _api_get(f"{GITHUB_API_ROOT}/repos/{owner}/{repo}")
    branch = info.get("default_branch")
    if not branch:
        raise GitHubFetchError(f"Could not determine default branch for {owner}/{repo}")
    return branch


def _get_filtered_tree(owner, repo, branch):
    tree_data = _api_get(
        f"{GITHUB_API_ROOT}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    )
    if tree_data.get("truncated"):
        print("[!] Warning: GitHub API tree response was truncated; some files may be skipped.")

    entries = []
    for node in tree_data.get("tree", []):
        if node.get("type") != "blob":
            continue
        path = node.get("path", "")
        if _is_excluded_path(path) or not _is_target_extension(path):
            continue
        entries.append(node)
    return entries


def _fetch_blob_text(blob_url):
    data = _api_get(blob_url)
    encoding = data.get("encoding")
    content = data.get("content", "")
    if encoding == "base64":
        try:
            raw_bytes = base64.b64decode(content)
        except (ValueError, TypeError) as e:
            raise GitHubFetchError(f"Base64 decode failed: {e}")
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return raw_bytes.decode("latin-1")
    raise GitHubFetchError(f"Unsupported blob encoding: {encoding}")


def fetch_repo_files(repo_url, mode="in-memory"):
    """
    Fetch scannable files from a GitHub repository.

    mode='in-memory': returns list of (virtual_path_str, text_content) tuples,
                       nothing written to disk.
    mode='file':       downloads files to ./<repo>_extracted_files/ preserving
                       relative paths, returns list of Path objects on disk.
    """
    owner, repo = _parse_repo_url(repo_url)
    print(f"[*] Resolving default branch for {owner}/{repo}...")
    branch = _get_default_branch(owner, repo)

    print(f"[*] Fetching repository tree ({branch})...")
    entries = _get_filtered_tree(owner, repo, branch)
    print(f"[*] {len(entries)} candidate file(s) after extension/exclusion filtering.")

    if mode == "in-memory":
        results = []
        for node in entries:
            path = node["path"]
            try:
                text = _fetch_blob_text(node["url"])
            except GitHubFetchError as e:
                print(f"[!] Skipping {path}: {e}")
                continue
            results.append((f"{repo}/{path}", text))
        return results

    if mode == "file":
        dest_root = Path(f"./{repo}_extracted_files")
        dest_root.mkdir(parents=True, exist_ok=True)
        written = []
        for node in entries:
            path = node["path"]
            try:
                text = _fetch_blob_text(node["url"])
            except GitHubFetchError as e:
                print(f"[!] Skipping {path}: {e}")
                continue
            dest_path = dest_root / path
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(dest_path, "w", encoding="utf-8") as f:
                    f.write(text)
            except OSError as e:
                print(f"[!] Failed to write {dest_path}: {e}")
                continue
            written.append(dest_path)
        return written

    raise GitHubFetchError(f"Unknown fetch mode: {mode}")
