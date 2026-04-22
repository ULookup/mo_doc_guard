from __future__ import annotations

import json
from pathlib import Path

from app.core.run_state import build_idempotency_key, generate_run_id
from app.graph.workflow import run_phase2, run_phase3


def test_generate_run_id_format() -> None:
    run_id = generate_run_id()
    assert run_id.startswith("run-")
    assert len(run_id) > len("run-20260101T000000Z-")


def test_build_idempotency_key() -> None:
    assert build_idempotency_key("v1.0.0", "v1.1.0") == "v1.0.0..v1.1.0"


def test_run_phase2_idempotency_skip(tmp_path: Path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    docs_repo_dir = tmp_path / "repos" / "matrixorigin.io"

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("MCP_AUTHOR_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("MCP_REVIEWER_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("DOCS_REPO_DIR", str(docs_repo_dir))
    monkeypatch.setenv("MATRIXORIGIN_DOCS_REPO", "git@github.com:matrixorigin/matrixorigin.io.git")
    monkeypatch.setattr("app.graph.langgraph_workflow.sync_docs_repo_main", lambda settings, dry_run: "sync-ok")
    monkeypatch.setattr(
        "app.agents.registry.MCPAuthorPlugin.run",
        lambda _self, _input: type(
            "AuthorOut",
            (),
            {
                "doc_patch_diff": "",
                "change_summary_md": "No changes.",
                "claims": {"claim_count": 0, "claims": []},
                "evidence_map": {},
            },
        )(),
    )
    monkeypatch.setattr(
        "app.agents.registry.MCPReviewerPlugin.run",
        lambda _self, _input: type(
            "ReviewerOut",
            (),
            {
                "decision": "approved",
                "comments": "approved",
                "blocking_issues": [],
                "review_report": {"decision": "pass", "claim_results": []},
                "verification_map": {},
            },
        )(),
    )

    first = run_phase2(
        prev_tag="v1.0.0",
        new_tag="v1.1.0",
        trigger_source="manual",
        dry_run=True,
    )
    assert first["status"] == "success"
    assert first["stage"] == "phase6_complete"

    second = run_phase2(
        prev_tag="v1.0.0",
        new_tag="v1.1.0",
        trigger_source="manual",
        dry_run=True,
    )
    assert second["status"] == "skipped"
    assert second["stage"] == "idempotency_check"

    run_state_files = list(runs_dir.glob("*/run_state.json"))
    assert len(run_state_files) == 2
    for state_file in run_state_files:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        assert state["idempotency_key"] == "v1.0.0..v1.1.0"


def test_dry_run_success_does_not_skip_real_run(tmp_path: Path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    docs_repo_dir = tmp_path / "repos" / "matrixorigin.io"

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("MCP_AUTHOR_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("MCP_REVIEWER_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("DOCS_REPO_DIR", str(docs_repo_dir))
    monkeypatch.setenv("MATRIXONE_REPO", "git@github.com:matrixorigin/matrixone.git")
    monkeypatch.setenv("MATRIXORIGIN_DOCS_REPO", "git@github.com:matrixorigin/matrixorigin.io.git")

    calls: list[bool] = []

    def fake_sync(settings, dry_run):
        calls.append(dry_run)
        return "sync-ok"

    monkeypatch.setattr("app.graph.langgraph_workflow.sync_docs_repo_main", fake_sync)
    monkeypatch.setattr(
        "app.agents.registry.MCPAuthorPlugin.run",
        lambda _self, _input: type(
            "AuthorOut",
            (),
            {
                "doc_patch_diff": "",
                "change_summary_md": "No changes.",
                "claims": {"claim_count": 0, "claims": []},
                "evidence_map": {},
            },
        )(),
    )
    monkeypatch.setattr(
        "app.agents.registry.MCPReviewerPlugin.run",
        lambda _self, _input: type(
            "ReviewerOut",
            (),
            {
                "decision": "approved",
                "comments": "approved",
                "blocking_issues": [],
                "review_report": {"decision": "pass", "claim_results": []},
                "verification_map": {},
            },
        )(),
    )
    monkeypatch.setattr(
        "app.graph.langgraph_workflow.collect_evidence_bundle",
        lambda **kwargs: {
            "mode": "normal",
            "commit_count": 0,
            "file_count": 0,
            "commits": [],
            "changed_files": [],
            "retrieval_scope": [],
        },
    )

    dry = run_phase2(
        prev_tag="v2.0.0",
        new_tag="v2.1.0",
        trigger_source="manual",
        dry_run=True,
    )
    assert dry["status"] == "success"

    real = run_phase2(
        prev_tag="v2.0.0",
        new_tag="v2.1.0",
        trigger_source="manual",
        dry_run=False,
    )
    assert real["status"] == "success"
    assert real["stage"] == "phase6_complete"
    assert calls == [True, False]


def test_phase3_writes_evidence_bundle(tmp_path: Path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    docs_repo_dir = tmp_path / "repos" / "matrixorigin.io"

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("MCP_AUTHOR_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("MCP_REVIEWER_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("DOCS_REPO_DIR", str(docs_repo_dir))
    monkeypatch.setenv("MATRIXORIGIN_DOCS_REPO", "git@github.com:matrixorigin/matrixorigin.io.git")
    monkeypatch.setattr("app.graph.langgraph_workflow.sync_docs_repo_main", lambda settings, dry_run: "sync-ok")
    monkeypatch.setattr(
        "app.agents.registry.MCPAuthorPlugin.run",
        lambda _self, _input: type(
            "AuthorOut",
            (),
            {
                "doc_patch_diff": "",
                "change_summary_md": "No changes.",
                "claims": {"claim_count": 0, "claims": []},
                "evidence_map": {},
            },
        )(),
    )
    monkeypatch.setattr(
        "app.agents.registry.MCPReviewerPlugin.run",
        lambda _self, _input: type(
            "ReviewerOut",
            (),
            {
                "decision": "approved",
                "comments": "approved",
                "blocking_issues": [],
                "review_report": {"decision": "pass", "claim_results": []},
                "verification_map": {},
            },
        )(),
    )

    result = run_phase3(
        prev_tag="v3.0.0",
        new_tag="v3.1.0",
        trigger_source="manual",
        dry_run=True,
    )

    assert result["status"] == "success"
    assert result["stage"] == "phase6_complete"

    run_dir = runs_dir / result["run_id"]
    evidence_file = run_dir / "evidence_bundle.json"
    assert evidence_file.exists()
    evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
    assert evidence["mode"] == "dry_run"
    assert evidence["prev_tag"] == "v3.0.0"
    assert evidence["new_tag"] == "v3.1.0"
    assert "release_notes" in evidence
    assert "diff_content" in evidence
    assert (run_dir / "doc_patch.diff").exists()
    assert (run_dir / "change_summary.md").exists()
    assert not (run_dir / "review_report.json").exists()
    assert (run_dir / "run_metrics.json").exists()
    assert result["pr_result"] == "skipped_no_substantive_change"
    assert not (run_dir / "pr_payload.json").exists()
    assert (runs_dir / "metrics_history.jsonl").exists()
    claims = json.loads((run_dir / "claims.json").read_text(encoding="utf-8"))
    assert "claims" in claims


def test_workflow_fails_when_reviewer_decision_is_fail(tmp_path: Path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    docs_repo_dir = tmp_path / "repos" / "matrixorigin.io"

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("MCP_AUTHOR_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("MCP_REVIEWER_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("DOCS_REPO_DIR", str(docs_repo_dir))
    monkeypatch.setenv("MATRIXORIGIN_DOCS_REPO", "git@github.com:matrixorigin/matrixorigin.io.git")
    monkeypatch.setattr("app.graph.langgraph_workflow.sync_docs_repo_main", lambda settings, dry_run: "sync-ok")
    monkeypatch.setattr(
        "app.agents.registry.MCPAuthorPlugin.run",
        lambda _self, _input: type(
            "AuthorOut",
            (),
            {
                "doc_patch_diff": (
                    "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/sql-syntax.md\n"
                    "@@ -1 +1 @@\n"
                    "+x\n"
                ),
                "change_summary_md": "need review",
                "claims": {
                    "claim_count": 1,
                    "claims": [
                        {
                            "claim_id": "C001",
                            "docs_path": "docs/sql-reference/sql-syntax.md",
                                "evidence": {
                                    "code_path": "pkg/sql/parsers/parser.go",
                                    "reason": "parser changed",
                                },
                        }
                    ],
                },
                "evidence_map": {},
            },
        )(),
    )
    monkeypatch.setattr(
        "app.graph.langgraph_workflow.get_pr_context",
        lambda **kwargs: {"context": "mock"},
    )
    monkeypatch.setattr(
        "app.agents.registry.MCPReviewerPlugin.run",
        lambda _self, _input: type(
            "ReviewerOut",
            (),
            {
                "decision": "changes_requested",
                "comments": "mock reviewer fail",
                "blocking_issues": ["mock reviewer fail"],
                "review_report": {"decision": "fail"},
                "verification_map": {},
            },
        )(),
    )

    result = run_phase3(
        prev_tag="v3.2.0",
        new_tag="v3.3.0",
        trigger_source="manual",
        dry_run=True,
    )
    assert result["status"] == "failed"
    assert result["decision"] == "fail"


def test_workflow_skips_pr_when_patch_empty(tmp_path: Path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    docs_repo_dir = tmp_path / "repos" / "matrixorigin.io"

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("MCP_AUTHOR_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("MCP_REVIEWER_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("DOCS_REPO_DIR", str(docs_repo_dir))
    monkeypatch.setenv("MATRIXORIGIN_DOCS_REPO", "git@github.com:matrixorigin/matrixorigin.io.git")
    monkeypatch.setattr("app.graph.langgraph_workflow.sync_docs_repo_main", lambda settings, dry_run: "sync-ok")
    monkeypatch.setattr(
        "app.agents.registry.MCPAuthorPlugin.run",
        lambda _self, _input: type(
            "AuthorOut",
            (),
            {
                "doc_patch_diff": "",
                "change_summary_md": "No changes.",
                "claims": {"claim_count": 0, "claims": []},
                "evidence_map": {},
            },
        )(),
    )
    monkeypatch.setattr(
        "app.agents.registry.MCPReviewerPlugin.run",
        lambda _self, _input: type(
            "ReviewerOut",
            (),
            {
                "decision": "approved",
                "comments": "approved",
                "blocking_issues": [],
                "review_report": {"decision": "pass", "claim_results": []},
                "verification_map": {},
            },
        )(),
    )

    result = run_phase3(
        prev_tag="v3.4.0",
        new_tag="v3.5.0",
        trigger_source="manual",
        dry_run=True,
    )
    assert result["status"] == "success"
    assert result["pr_result"] == "skipped_no_substantive_change"


def test_workflow_passes_enriched_evidence_to_author_input(tmp_path: Path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    docs_repo_dir = tmp_path / "repos" / "matrixorigin.io"

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("MCP_AUTHOR_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("MCP_REVIEWER_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("DOCS_REPO_DIR", str(docs_repo_dir))
    monkeypatch.setenv("MATRIXORIGIN_DOCS_REPO", "git@github.com:matrixorigin/matrixorigin.io.git")
    monkeypatch.setattr("app.graph.langgraph_workflow.sync_docs_repo_main", lambda settings, dry_run: "sync-ok")
    monkeypatch.setattr(
        "app.graph.langgraph_workflow.collect_evidence_bundle",
        lambda **kwargs: {
            "mode": "normal",
            "commit_count": 1,
            "file_count": 1,
            "commits": [{"sha": "abc", "subject": "parser fix"}],
            "changed_files": ["pkg/sql/parsers/parser.go"],
            "retrieval_scope": [],
            "release_notes": "Release range: v1.0.0..v1.1.0",
            "diff_content": "diff --git a/pkg/sql/parsers/parser.go b/pkg/sql/parsers/parser.go",
        },
    )
    captured: dict[str, str] = {}

    def fake_author(_self, payload):
        captured["release_notes"] = payload.release_notes
        captured["diff_content"] = payload.diff_content
        return type(
            "AuthorOut",
            (),
            {
                "doc_patch_diff": "",
                "change_summary_md": "No changes.",
                "claims": {"claim_count": 0, "claims": []},
                "evidence_map": {},
            },
        )()

    monkeypatch.setattr("app.agents.registry.MCPAuthorPlugin.run", fake_author)

    result = run_phase3(
        prev_tag="v1.0.0",
        new_tag="v1.1.0",
        trigger_source="manual",
        dry_run=True,
    )
    assert result["status"] == "success"
    assert captured["release_notes"] != ""
    assert captured["diff_content"] != ""
