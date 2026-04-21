"""Collect tag-diff evidence from matrixone repository."""

from __future__ import annotations

from datetime import UTC, datetime
import subprocess
from pathlib import Path
from typing import Any, Sequence

from app.core.settings import Settings
from app.retrieval.incremental_scope import build_retrieval_scope, load_path_mappings


def _run_git(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _ensure_matrixone_repo(settings: Settings, dry_run: bool) -> None:
    repo_dir = settings.matrixone_repo_dir
    repo_url = settings.matrixone_repo
    git_dir = repo_dir / ".git"

    if git_dir.exists():
        return

    if dry_run:
        return

    if not repo_url:
        raise ValueError("MATRIXONE_REPO is required when dry_run=false")

    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    _run_git(["git", "clone", repo_url, str(repo_dir)], cwd=repo_dir.parent)


def resolve_prev_tag(
    settings: Settings,
    new_tag: str,
    prev_tag: str | None,
    dry_run: bool,
) -> str:
    if prev_tag:
        return prev_tag

    if dry_run:
        return "__dry_run_prev_tag__"

    _ensure_matrixone_repo(settings=settings, dry_run=dry_run)

    tag_result = _run_git(
        ["git", "tag", "--sort=version:refname"],
        cwd=settings.matrixone_repo_dir,
    )
    tags = [line.strip() for line in tag_result.stdout.splitlines() if line.strip()]
    if new_tag not in tags:
        raise ValueError(f"new_tag {new_tag} does not exist in matrixone repo")

    idx = tags.index(new_tag)
    if idx == 0:
        raise ValueError(f"new_tag {new_tag} has no previous tag")
    return tags[idx - 1]


def collect_evidence_bundle(
    settings: Settings,
    prev_tag: str,
    new_tag: str,
    dry_run: bool,
    path_mapping_file: Path,
) -> dict[str, Any]:
    if dry_run:
        return {
            "mode": "dry_run",
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "prev_tag": prev_tag,
            "new_tag": new_tag,
            "commit_count": 0,
            "file_count": 0,
            "commits": [],
            "changed_files": [],
            "retrieval_scope": [],
        }

    _ensure_matrixone_repo(settings=settings, dry_run=False)

    repo_dir = settings.matrixone_repo_dir
    commits_result = _run_git(
        ["git", "log", "--pretty=format:%H%x1f%s", f"{prev_tag}..{new_tag}"],
        cwd=repo_dir,
    )
    commits: list[dict[str, str]] = []
    for line in commits_result.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f", maxsplit=1)
        sha = parts[0]
        subject = parts[1] if len(parts) > 1 else ""
        commits.append({"sha": sha, "subject": subject})

    files_result = _run_git(
        ["git", "diff", "--name-only", f"{prev_tag}..{new_tag}"],
        cwd=repo_dir,
    )
    changed_files = [line.strip() for line in files_result.stdout.splitlines() if line.strip()]
    path_mappings = load_path_mappings(path_mapping_file)
    retrieval_scope = build_retrieval_scope(changed_files, path_mappings)

    return {
        "mode": "normal",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "prev_tag": prev_tag,
        "new_tag": new_tag,
        "commit_count": len(commits),
        "file_count": len(changed_files),
        "commits": commits,
        "changed_files": changed_files,
        "retrieval_scope": retrieval_scope,
    }
