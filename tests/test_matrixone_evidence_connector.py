from __future__ import annotations

from pathlib import Path
import subprocess

from app.connectors.matrixone_evidence import collect_evidence_bundle
from app.core.settings import Settings
from app.connectors.model_router import ModelRouter


def _build_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="dev",
        log_level="INFO",
        runs_dir=tmp_path / "runs",
        matrixone_repo_dir=tmp_path / "repos" / "matrixone",
        docs_repo_dir=tmp_path / "repos" / "matrixorigin.io",
        path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
        agents_config_path=Path("configs/agents.yaml").resolve(),
        models_config_path=Path("configs/models.yaml").resolve(),
        prompts_config_path=Path("configs/prompts.yaml").resolve(),
        quality_gates_config_path=Path("configs/quality_gates.yaml").resolve(),
        matrixone_repo="",
        matrixorigin_docs_repo="",
        openai_api_key="",
        anthropic_api_key="",
        docs_repo_token="",
        model_router=ModelRouter(Path("configs/models.yaml").resolve()),
    )


def test_collect_evidence_bundle_contains_release_notes_and_diff(monkeypatch, tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    (settings.matrixone_repo_dir / ".git").mkdir(parents=True)

    def fake_run_git(args, cwd):
        if args[:2] == ["git", "log"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="sha1\x1fparser: fix behavior\nsha2\x1ffrontend: tune vars\n",
                stderr="",
            )
        if args[:3] == ["git", "diff", "--name-only"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="pkg/sql/parsers/parser.go\npkg/frontend/variables/system_vars.go\n",
                stderr="",
            )
        if args[:3] == ["git", "diff", "--unified=0"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="diff --git a/pkg/sql/parsers/parser.go b/pkg/sql/parsers/parser.go\n@@ -1 +1 @@\n+x\n",
                stderr="",
            )
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr("app.connectors.matrixone_evidence._run_git", fake_run_git)
    bundle = collect_evidence_bundle(
        settings=settings,
        prev_tag="v1.0.0",
        new_tag="v1.1.0",
        dry_run=False,
        path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
    )
    assert bundle["release_notes"] != ""
    assert "Release range: v1.0.0..v1.1.0" in bundle["release_notes"]
    assert "diff --git" in bundle["diff_content"]


def test_collect_evidence_bundle_uses_safe_diff_truncation(monkeypatch, tmp_path: Path) -> None:
    settings = _build_settings(tmp_path)
    (settings.matrixone_repo_dir / ".git").mkdir(parents=True)
    monkeypatch.setenv("EVIDENCE_DIFF_MAX_CHARS", "-1")

    def fake_run_git(args, cwd):
        if args[:2] == ["git", "log"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if args[:3] == ["git", "diff", "--name-only"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        if args[:3] == ["git", "diff", "--unified=0"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="x" * 1500,
                stderr="",
            )
        raise AssertionError(f"unexpected git args: {args}")

    monkeypatch.setattr("app.connectors.matrixone_evidence._run_git", fake_run_git)
    bundle = collect_evidence_bundle(
        settings=settings,
        prev_tag="v1.0.0",
        new_tag="v1.1.0",
        dry_run=False,
        path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
    )
    assert "... [truncated at 1000 chars]" in bundle["diff_content"]

