"""Collect tag-diff evidence from matrixone repository."""

from __future__ import annotations

from datetime import UTC, datetime
import os
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
            "release_notes": "",
            "diff_content": "",
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
    diff_content = _collect_diff_content(repo_dir, prev_tag, new_tag)
    release_notes = _build_release_notes(prev_tag, new_tag, commits, changed_files)

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
        "release_notes": release_notes,
        "diff_content": diff_content,
    }


def _collect_diff_content(repo_dir: Path, prev_tag: str, new_tag: str) -> str:
    max_chars = _safe_max_chars(os.getenv("EVIDENCE_DIFF_MAX_CHARS", "12000"))
    diff_result = _run_git(
        ["git", "diff", "--unified=0", f"{prev_tag}..{new_tag}"],
        cwd=repo_dir,
    )
    raw = diff_result.stdout
    if len(raw) <= max_chars:
        return raw
    truncated = raw[:max_chars]
    return f"{truncated}\n\n... [truncated at {max_chars} chars]"


def _build_release_notes(
    prev_tag: str,
    new_tag: str,
    commits: list[dict[str, str]],
    changed_files: list[str],
) -> str:
    lines = [
        f"Release range: {prev_tag}..{new_tag}",
        f"Commits: {len(commits)}",
        f"Changed files: {len(changed_files)}",
        "",
        "Commit subjects:",
    ]
    for commit in commits[:20]:
        subject = commit.get("subject", "").strip() or "<empty subject>"
        lines.append(f"- {subject}")
    if len(commits) > 20:
        lines.append(f"- ... and {len(commits) - 20} more commits")
    return "\n".join(lines).strip() + "\n"


def _safe_max_chars(raw_value: str) -> int:
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        return 12000
    return max(1000, parsed)
