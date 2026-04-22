"""Git operations for syncing docs repository to origin/main."""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
import re
from typing import Sequence
from urllib.parse import quote

from app.core.settings import Settings

logger = logging.getLogger(__name__)


def _run_git(args: Sequence[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    timeout_seconds = _env_float("DOCS_SYNC_GIT_TIMEOUT_SECONDS", 120.0, minimum=1.0)
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(
            f"git command failed in docs sync: {' '.join(args)} (exit={exc.returncode}) stderr={stderr[:400]}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"git command failed in docs sync: {' '.join(args)} timed out after {int(timeout_seconds)}s"
        ) from exc


def sync_docs_repo_main(settings: Settings, dry_run: bool = True) -> str:
    target_dir = settings.docs_repo_dir
    repo_url = settings.matrixorigin_docs_repo

    if dry_run:
        source = repo_url or "<unset:MATRIXORIGIN_DOCS_REPO>"
        return f"dry-run: sync {source} -> {target_dir} on origin/main"

    if not repo_url:
        raise ValueError("MATRIXORIGIN_DOCS_REPO is required to sync docs repository")
    token = settings.docs_repo_token.strip()
    if not token:
        raise ValueError("DOCS_REPO_TOKEN is required to sync docs repository")
    normalized_repo_url = _normalize_repo_url_to_https(repo_url)
    auth_repo_url = _authenticated_repo_url(normalized_repo_url, token)

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    git_dir = target_dir / ".git"

    if git_dir.exists():
        remote_result = _run_git(["git", "remote", "get-url", "origin"], cwd=target_dir)
        origin_url = remote_result.stdout.strip()
        if _normalize_repo_url_to_https(origin_url) != normalized_repo_url:
            raise ValueError(
                f"DOCS_REPO_DIR origin mismatch: expected {normalized_repo_url}, got {origin_url}"
            )

        _run_fetch_with_retry(
            ["git", "fetch", auth_repo_url, "main", "--prune"],
            cwd=target_dir,
        )
        _run_git(["git", "checkout", "main"], cwd=target_dir)
        _run_git(["git", "reset", "--hard", "FETCH_HEAD"], cwd=target_dir)
        _run_git(["git", "clean", "-fd"], cwd=target_dir)
        return f"synced existing repo at {target_dir}"

    _run_git(
        [
            "git",
            "clone",
            "--branch",
            "main",
            "--single-branch",
            auth_repo_url,
            str(target_dir),
        ],
    )
    _run_git(["git", "remote", "set-url", "origin", normalized_repo_url], cwd=target_dir)
    return f"cloned repo into {target_dir}"


def _normalize_repo_url_to_https(repo_url: str) -> str:
    stripped = repo_url.strip()
    ssh_match = re.match(r"git@github\.com:(.+?)(?:\.git)?$", stripped)
    if ssh_match:
        return f"https://github.com/{ssh_match.group(1)}.git"
    https_match = re.match(r"https://github\.com/(.+?)(?:\.git)?$", stripped)
    if https_match:
        return f"https://github.com/{https_match.group(1)}.git"
    raise ValueError(f"unsupported github repo url: {repo_url}")


def _authenticated_repo_url(https_repo_url: str, token: str) -> str:
    encoded = quote(token, safe="")
    return https_repo_url.replace("https://", f"https://x-access-token:{encoded}@")


def _run_fetch_with_retry(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    attempts = _env_int("DOCS_SYNC_FETCH_RETRIES", 3, minimum=1)
    backoff_seconds = _env_float("DOCS_SYNC_FETCH_BACKOFF_SECONDS", 2.0, minimum=0.0)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            logger.info("docs_sync.fetch.attempt started attempt=%s/%s cwd=%s", attempt, attempts, cwd)
            return _run_git(args, cwd=cwd)
        except RuntimeError as exc:
            last_error = exc
            if not _is_transient_git_network_error(str(exc)) or attempt == attempts:
                logger.error(
                    "docs_sync.fetch.attempt failed attempt=%s/%s retryable=%s error=%s",
                    attempt,
                    attempts,
                    _is_transient_git_network_error(str(exc)),
                    str(exc),
                )
                raise
            logger.warning(
                "docs_sync.fetch.attempt retrying attempt=%s/%s sleep_seconds=%.1f error=%s",
                attempt,
                attempts,
                backoff_seconds * attempt,
                str(exc),
            )
            time.sleep(backoff_seconds * attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("git fetch failed without a specific error")


def _is_transient_git_network_error(message: str) -> bool:
    lowered = message.lower()
    transient_markers = [
        "timed out",
        "couldn't connect",
        "failed to connect",
        "connection reset",
        "rpc failed",
        "curl 28",
        "http2 framing layer",
        "tls",
        "temporarily unavailable",
        "bad gateway",
    ]
    return any(marker in lowered for marker in transient_markers)


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, value)


