"""Shared LangGraph state for dual-agent documentation workflow."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


ReviewResult = Literal["approved", "changes_requested", "rejected"]


class DocUpdateState(TypedDict, total=False):
    latest_tag: str
    prev_tag: str
    diff_content: str
    release_notes: str
    generated_docs: dict[str, Any]
    pr_url: str
    review_result: ReviewResult
    review_comments: str

    run_id: str
    idempotency_key: str
    trigger_source: str
    dry_run: bool
    stage: str
    status: str
    decision: str | None
    artifacts: list[str]
    blocking_issues: list[str]
    retry_count: int
    max_retry_count: int

    evidence_bundle: dict[str, Any]
    claims: dict[str, Any]
    review_report: dict[str, Any]
    doc_patch_diff: str
    change_summary_md: str
    gate_report: dict[str, Any]
    pr_payload: dict[str, Any]
    pr_result: str
    pr_branch: str
    pr_title: str
    pr_body: str

    error: str

    # runtime objects, not persisted in final artifacts
    settings: Any
    store: Any
    run_context: Any
    started_at: Any
    ended_at: Any
    agent_router: Any
