from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from app.connectors.github_pr import create_docs_pr


def test_create_docs_pr_dry_run_returns_simulated_payload() -> None:
    result = create_docs_pr(
        docs_repo_url="git@github.com:matrixorigin/matrixorigin.io.git",
        docs_repo_dir=Path("."),
        doc_patch_diff="",
        branch_name="docs/auto/v1-run",
        base_branch="main",
        title="docs: sync v1..v2",
        body="test",
        commit_message="test commit",
        dry_run=True,
    )
    assert result["mode"] == "dry_run"
    assert result["simulated"] is True
    assert result["pr_created"] is False


def test_create_docs_pr_real_mode_requires_token(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="DOCS_REPO_TOKEN"):
        create_docs_pr(
            docs_repo_url="git@github.com:matrixorigin/matrixorigin.io.git",
            docs_repo_dir=tmp_path,
            doc_patch_diff="diff --git a/docs/a.md b/docs/a.md\n",
            branch_name="docs/auto/v1-run",
            base_branch="main",
            title="docs: sync v1..v2",
            body="test",
            commit_message="test commit",
            dry_run=False,
        )


def test_create_docs_pr_real_mode_with_no_changes(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("DOCS_REPO_TOKEN", "token")

    def fake_run(args, cwd=None, check=False, capture_output=True, text=True, env=None):
        if args[:3] == ["git", "diff", "--cached"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    result = create_docs_pr(
        docs_repo_url="git@github.com:matrixorigin/matrixorigin.io.git",
        docs_repo_dir=tmp_path,
        doc_patch_diff="diff --git a/docs/a.md b/docs/a.md\n",
        branch_name="docs/auto/v1-run",
        base_branch="main",
        title="docs: sync v1..v2",
        body="test",
        commit_message="test commit",
        dry_run=False,
    )
    assert result["mode"] == "real"
    assert result["pr_created"] is False
    assert result["no_changes"] is True


def test_create_docs_pr_real_mode_success(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.setenv("DOCS_REPO_TOKEN", "token")
    seen_commands: list[list[str]] = []

    def fake_run(args, cwd=None, check=False, capture_output=True, text=True, env=None):
        seen_commands.append(list(args))
        if args[:3] == ["git", "diff", "--cached"]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
        if args[:3] == ["gh", "pr", "create"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="https://github.com/matrixorigin/matrixorigin.io/pull/123\n",
                stderr="",
            )
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    result = create_docs_pr(
        docs_repo_url="git@github.com:matrixorigin/matrixorigin.io.git",
        docs_repo_dir=tmp_path,
        doc_patch_diff="diff --git a/docs/a.md b/docs/a.md\n@@ -1 +1 @@\n+x\n",
        branch_name="docs/auto/v1-run",
        base_branch="main",
        title="docs: sync v1..v2",
        body="test",
        commit_message="test commit",
        dry_run=False,
    )

    assert result["mode"] == "real"
    assert result["pr_created"] is True
    assert result["pr_url"].endswith("/pull/123")
    assert [
        "git",
        "push",
        "-u",
        "https://x-access-token:token@github.com/matrixorigin/matrixorigin.io.git",
        "docs/auto/v1-run",
    ] in seen_commands
