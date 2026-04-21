"""PR creation connector for docs repository."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any
from urllib.parse import quote


def create_docs_pr(
    *,
    docs_repo_url: str,
    docs_repo_dir: Path,
    doc_patch_diff: str,
    branch_name: str,
    base_branch: str,
    title: str,
    body: str,
    commit_message: str,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {
            "pr_created": False,
            "simulated": True,
            "mode": "dry_run",
            "pr_url": f"dry-run://{_repo_slug(docs_repo_url)}/pull/{branch_name}",
        }

    token = _require_docs_repo_token()
    auth_repo_url = _authenticated_repo_url(docs_repo_url, token)
    if not (docs_repo_dir / ".git").exists():
        raise ValueError(f"docs repo is not initialized: {docs_repo_dir}")
    if not doc_patch_diff.strip():
        return {
            "pr_created": False,
            "simulated": False,
            "mode": "real",
            "pr_url": "",
            "no_changes": True,
        }

    changed = _apply_patch_and_commit(
        docs_repo_dir=docs_repo_dir,
        branch_name=branch_name,
        base_branch=base_branch,
        doc_patch_diff=doc_patch_diff,
        commit_message=commit_message,
        auth_repo_url=auth_repo_url,
    )
    if not changed:
        return {
            "pr_created": False,
            "simulated": False,
            "mode": "real",
            "pr_url": "",
            "no_changes": True,
        }
    _run_git(["git", "push", "-u", auth_repo_url, branch_name], cwd=docs_repo_dir)

    repo = _repo_slug(docs_repo_url)
    command = [
        "gh",
        "pr",
        "create",
        "--repo",
        repo,
        "--head",
        branch_name,
        "--base",
        base_branch,
        "--title",
        title,
        "--body",
        body,
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env=_gh_env(),
    )
    pr_url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    return {
        "pr_created": True,
        "simulated": False,
        "mode": "real",
        "pr_url": pr_url,
        "no_changes": False,
    }


def update_docs_pr_branch(
    *,
    docs_repo_url: str,
    docs_repo_dir: Path,
    branch_name: str,
    doc_patch_diff: str,
    commit_message: str,
    dry_run: bool,
) -> dict[str, Any]:
    if dry_run:
        return {"updated": True, "simulated": True}
    token = _require_docs_repo_token()
    auth_repo_url = _authenticated_repo_url(docs_repo_url, token)
    if not branch_name:
        raise ValueError("branch_name is required to update PR branch")
    _run_git(["git", "checkout", branch_name], cwd=docs_repo_dir)
    changed = _apply_patch_and_commit(
        docs_repo_dir=docs_repo_dir,
        branch_name=branch_name,
        base_branch="",
        doc_patch_diff=doc_patch_diff,
        commit_message=commit_message,
        reset_branch=False,
        auth_repo_url=auth_repo_url,
    )
    if not changed:
        return {"updated": False, "no_changes": True, "simulated": False}
    _run_git(["git", "push", auth_repo_url, branch_name], cwd=docs_repo_dir)
    return {"updated": True, "simulated": False}


def get_pr_context(*, pr_url: str, dry_run: bool, docs_repo_dir: Path) -> dict[str, Any]:
    if dry_run:
        return {"mode": "dry_run", "pr_url": pr_url, "changes": ""}
    if not pr_url:
        return {"mode": "real", "pr_url": "", "changes": ""}
    result = subprocess.run(
        ["gh", "pr", "view", pr_url, "--json", "files,commits,body,title,headRefName,baseRefName"],
        cwd=docs_repo_dir,
        check=True,
        capture_output=True,
        text=True,
        env=_gh_env(),
    )
    return {"mode": "real", "pr_url": pr_url, "context": result.stdout}


def approve_pr(*, pr_url: str, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"approved": True, "simulated": True}
    if not pr_url:
        return {"approved": False, "simulated": False}
    result = subprocess.run(
        ["gh", "pr", "review", pr_url, "--approve"],
        check=True,
        capture_output=True,
        text=True,
        env=_gh_env(),
    )
    return {"approved": True, "simulated": False, "output": result.stdout}


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True, env=env)


def _require_docs_repo_token() -> str:
    token = os.getenv("DOCS_REPO_TOKEN", "").strip()
    if not token:
        raise ValueError("DOCS_REPO_TOKEN is required when dry_run=false")
    return token


def _gh_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GH_TOKEN"] = _require_docs_repo_token()
    # Enforce docs token path and avoid accidental fallback.
    env.pop("GITHUB_TOKEN", None)
    return env


def _apply_patch_and_commit(
    *,
    docs_repo_dir: Path,
    branch_name: str,
    base_branch: str,
    doc_patch_diff: str,
    commit_message: str,
    auth_repo_url: str,
    reset_branch: bool = True,
) -> bool:
    if reset_branch:
        _run_git(["git", "checkout", base_branch], cwd=docs_repo_dir)
        _run_git(["git", "fetch", auth_repo_url, base_branch, "--prune"], cwd=docs_repo_dir)
        _run_git(["git", "reset", "--hard", "FETCH_HEAD"], cwd=docs_repo_dir)
        _run_git(["git", "checkout", "-B", branch_name], cwd=docs_repo_dir)

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".diff",
        dir=docs_repo_dir,
        delete=False,
        encoding="utf-8",
    ) as patch_file:
        patch_file.write(doc_patch_diff)
        patch_path = Path(patch_file.name)
    try:
        _run_git(["git", "apply", str(patch_path)], cwd=docs_repo_dir)
    finally:
        patch_path.unlink(missing_ok=True)

    _run_git(["git", "add", "-A"], cwd=docs_repo_dir)
    if not _has_staged_changes(docs_repo_dir):
        return False
    _run_git(["git", "commit", "-m", commit_message], cwd=docs_repo_dir)
    return True


def _has_staged_changes(repo_dir: Path) -> bool:
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode != 0


def _repo_slug(repo_url: str) -> str:
    stripped = repo_url.strip()
    # git@github.com:owner/repo.git
    ssh_match = re.match(r"git@github\.com:(.+?)(?:\.git)?$", stripped)
    if ssh_match:
        return ssh_match.group(1)
    # https://github.com/owner/repo.git
    https_match = re.match(r"https://github\.com/(.+?)(?:\.git)?$", stripped)
    if https_match:
        return https_match.group(1)
    raise ValueError(f"unsupported github repo url: {repo_url}")


def _normalize_repo_url_to_https(repo_url: str) -> str:
    stripped = repo_url.strip()
    ssh_match = re.match(r"git@github\.com:(.+?)(?:\.git)?$", stripped)
    if ssh_match:
        return f"https://github.com/{ssh_match.group(1)}.git"
    https_match = re.match(r"https://github\.com/(.+?)(?:\.git)?$", stripped)
    if https_match:
        return f"https://github.com/{https_match.group(1)}.git"
    raise ValueError(f"unsupported github repo url: {repo_url}")


def _authenticated_repo_url(repo_url: str, token: str) -> str:
    https_url = _normalize_repo_url_to_https(repo_url)
    encoded = quote(token, safe="")
    return https_url.replace("https://", f"https://x-access-token:{encoded}@")
