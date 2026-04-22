from __future__ import annotations

import json
from pathlib import Path

from app.graph.langgraph_workflow import _create_pr_route
from app.graph.workflow import run_phase6


def test_langgraph_happy_path_generates_review_and_pr_payload(tmp_path: Path, monkeypatch) -> None:
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
                    "+new content\n"
                ),
                "change_summary_md": "summary",
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
        "app.agents.registry.MCPReviewerPlugin.run",
        lambda _self, _input: type(
            "ReviewerOut",
            (),
            {
                "decision": "approved",
                "comments": "ok",
                "blocking_issues": [],
                "review_report": {"decision": "pass", "claim_results": [{"status": "pass"}]},
                "verification_map": {},
            },
        )(),
    )
    monkeypatch.setattr("app.graph.langgraph_workflow.get_pr_context", lambda **kwargs: {"mock": True})

    result = run_phase6(prev_tag="v1.0.0", new_tag="v1.1.0", trigger_source="manual", dry_run=True)
    assert result["status"] == "success"
    assert result["decision"] == "pass"
    run_dir = runs_dir / result["run_id"]
    assert (run_dir / "review_report.json").exists()
    assert (run_dir / "pr_payload.json").exists()


def test_langgraph_reviewer_loop_reaches_reject(tmp_path: Path, monkeypatch) -> None:
    runs_dir = tmp_path / "runs"
    docs_repo_dir = tmp_path / "repos" / "matrixorigin.io"

    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("MCP_AUTHOR_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("MCP_REVIEWER_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("RUNS_DIR", str(runs_dir))
    monkeypatch.setenv("DOCS_REPO_DIR", str(docs_repo_dir))
    monkeypatch.setenv("MATRIXORIGIN_DOCS_REPO", "git@github.com:matrixorigin/matrixorigin.io.git")
    monkeypatch.setattr("app.graph.langgraph_workflow.sync_docs_repo_main", lambda settings, dry_run: "sync-ok")
    monkeypatch.setattr("app.graph.langgraph_workflow.get_pr_context", lambda **kwargs: {"mock": True})
    monkeypatch.setattr(
        "app.agents.registry.AgentRegistry.max_revision_loops",
        lambda _self: 1,
    )
    monkeypatch.setattr(
        "app.agents.registry.MCPAuthorPlugin.run",
        lambda _self, _input: type(
            "AuthorOut",
            (),
            {
                "doc_patch_diff": (
                    "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/sql-syntax.md\n"
                    "@@ -1 +1 @@\n"
                    "+new content\n"
                ),
                "change_summary_md": "summary",
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
        "app.agents.registry.MCPReviewerPlugin.run",
        lambda _self, _input: type(
            "ReviewerOut",
            (),
            {
                "decision": "changes_requested",
                "comments": "need fix",
                "blocking_issues": ["evidence mismatch"],
                "review_report": {"decision": "fail", "claim_results": [{"status": "fail"}]},
                "verification_map": {},
            },
        )(),
    )

    result = run_phase6(prev_tag="v1.0.0", new_tag="v1.2.0", trigger_source="manual", dry_run=True)
    assert result["status"] == "failed"
    assert result["decision"] == "fail"

    run_dir = runs_dir / result["run_id"]
    state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
    assert "review loop exceeded max retries" in state.get("blocking_issues", [])


def test_create_pr_route_skips_on_blocked_or_failed() -> None:
    assert _create_pr_route({"pr_result": "blocked"}) == "skip_review"
    assert _create_pr_route({"status": "failed", "pr_result": "created"}) == "skip_review"
    assert _create_pr_route({"pr_result": "created"}) == "to_review"
