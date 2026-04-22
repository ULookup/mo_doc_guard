"""LangGraph-based dual-agent workflow implementation."""

from __future__ import annotations

import json
import time

from langgraph.graph import END, StateGraph

from app.agents.base import AuthorAgentInput, ReviewerAgentInput
from app.connectors.docs_repo_sync import sync_docs_repo_main
from app.connectors.github_pr import approve_pr, create_docs_pr, get_pr_context, update_docs_pr_branch
from app.connectors.matrixone_evidence import collect_evidence_bundle, resolve_prev_tag
from app.core.quality_gate import evaluate_quality_gate
from app.core.run_state import create_run_context
from app.graph.state import DocUpdateState


def build_langgraph_app():
    graph = StateGraph(DocUpdateState)
    graph.add_node("fetch_changes", fetch_changes)
    graph.add_node("analyze_and_generate", analyze_and_generate)
    graph.add_node("create_pr", create_pr_node)
    graph.add_node("review_pr", review_pr_node)
    graph.add_node("revise_docs", revise_docs_node)
    graph.add_node("approve_pr", approve_pr_node)

    graph.set_entry_point("fetch_changes")
    graph.add_conditional_edges(
        "fetch_changes",
        _fetch_route,
        {
            "skipped": END,
            "continue": "analyze_and_generate",
        },
    )
    graph.add_edge("analyze_and_generate", "create_pr")
    graph.add_conditional_edges(
        "create_pr",
        _create_pr_route,
        {
            "skip_review": END,
            "to_review": "review_pr",
        },
    )
    graph.add_conditional_edges(
        "review_pr",
        _review_route,
        {
            "approved": "approve_pr",
            "changes_requested": "revise_docs",
            "rejected": END,
        },
    )
    graph.add_edge("revise_docs", "review_pr")
    graph.add_edge("approve_pr", END)
    return graph.compile()


def fetch_changes(state: DocUpdateState) -> DocUpdateState:
    settings = state["settings"]
    store = state["store"]
    dry_run = bool(state["dry_run"])
    trigger_source = str(state["trigger_source"])
    new_tag = str(state["latest_tag"])
    prev_tag = str(state.get("prev_tag", "")).strip() or None

    resolved_prev_tag = resolve_prev_tag(
        settings=settings,
        new_tag=new_tag,
        prev_tag=prev_tag,
        dry_run=dry_run,
    )
    context = create_run_context(settings.runs_dir, resolved_prev_tag, new_tag)
    run_state = store.initialize(context, trigger_source, dry_run=dry_run)
    _log_event(
        store,
        context,
        event="run_started",
        stage="fetch_changes",
        prev_tag=resolved_prev_tag,
        new_tag=new_tag,
        dry_run=dry_run,
    )

    include_dry_run = dry_run
    if store.has_successful_run(context.idempotency_key, include_dry_run=include_dry_run):
        run_state = store.patch_state(
            context.run_state_path,
            stage="idempotency_check",
            status="skipped",
            decision="skip",
            artifacts=["run_state.json", "pipeline.log"],
        )
        _log_event(
            store,
            context,
            event="idempotency_skipped",
            stage="idempotency_check",
            idempotency_key=context.idempotency_key,
        )
        return {
            **state,
            "prev_tag": resolved_prev_tag,
            "run_id": context.run_id,
            "idempotency_key": context.idempotency_key,
            "run_context": context,
            "status": run_state["status"],
            "stage": run_state["stage"],
            "decision": run_state.get("decision"),
            "artifacts": run_state.get("artifacts", []),
            "review_result": "rejected",
        }

    run_state = store.patch_state(
        context.run_state_path,
        stage="fetch_changes",
        status="running",
    )
    return {
        **state,
        "prev_tag": resolved_prev_tag,
        "run_id": context.run_id,
        "idempotency_key": context.idempotency_key,
        "run_context": context,
        "status": run_state["status"],
        "stage": run_state["stage"],
        "retry_count": 0,
        "max_retry_count": int(state.get("max_retry_count", 2)),
    }


def analyze_and_generate(state: DocUpdateState) -> DocUpdateState:
    settings = state["settings"]
    store = state["store"]
    context = state["run_context"]
    router = state["agent_router"]
    dry_run = bool(state["dry_run"])

    run_state = store.patch_state(context.run_state_path, stage="sync_docs_repo_main", status="running")
    sync_started_at = time.perf_counter()
    _log_event(store, context, event="stage_started", stage="sync_docs_repo_main")
    sync_result = sync_docs_repo_main(settings=settings, dry_run=dry_run)
    _log_event(
        store,
        context,
        event="stage_finished",
        stage="sync_docs_repo_main",
        elapsed_ms=_elapsed_ms(sync_started_at),
        result=sync_result,
    )

    run_state = store.patch_state(context.run_state_path, stage="collect_evidence", status="running")
    evidence_started_at = time.perf_counter()
    _log_event(store, context, event="stage_started", stage="collect_evidence")
    evidence_bundle = collect_evidence_bundle(
        settings=settings,
        prev_tag=str(state["prev_tag"]),
        new_tag=str(state["latest_tag"]),
        dry_run=dry_run,
        path_mapping_file=settings.path_mapping_file,
    )
    evidence_path = context.run_dir / "evidence_bundle.json"
    evidence_path.write_text(json.dumps(evidence_bundle, ensure_ascii=True, indent=2), encoding="utf-8")
    _log_event(
        store,
        context,
        event="stage_finished",
        stage="collect_evidence",
        elapsed_ms=_elapsed_ms(evidence_started_at),
        commit_count=evidence_bundle.get("commit_count", 0),
        file_count=evidence_bundle.get("file_count", 0),
    )

    run_state = store.patch_state(context.run_state_path, stage="writer_agent", status="running")
    author_started_at = time.perf_counter()
    _log_event(store, context, event="stage_started", stage="writer_agent")
    author_out = router.run_author(
        AuthorAgentInput(
            prev_tag=str(state["prev_tag"]),
            new_tag=str(state["latest_tag"]),
            evidence_bundle=evidence_bundle,
            release_notes=str(evidence_bundle.get("release_notes", "")),
            diff_content=str(evidence_bundle.get("diff_content", "")),
            review_feedback=None,
        )
    )

    doc_patch_path = context.run_dir / "doc_patch.diff"
    change_summary_path = context.run_dir / "change_summary.md"
    claims_path = context.run_dir / "claims.json"
    doc_patch_path.write_text(author_out.doc_patch_diff, encoding="utf-8")
    change_summary_path.write_text(author_out.change_summary_md, encoding="utf-8")
    claims_path.write_text(json.dumps(author_out.claims, ensure_ascii=True, indent=2), encoding="utf-8")
    _log_event(
        store,
        context,
        event="stage_finished",
        stage="writer_agent",
        elapsed_ms=_elapsed_ms(author_started_at),
        claim_count=author_out.claims.get("claim_count", 0),
        patch_size_chars=len(author_out.doc_patch_diff),
    )

    run_state = store.patch_state(
        context.run_state_path,
        stage=run_state["stage"],
        status="running",
        sync_result=sync_result,
        evidence_result=f"wrote {evidence_path.name}",
        writer_result=f"wrote {doc_patch_path.name}, {change_summary_path.name}, {claims_path.name}",
        artifacts=[
            "run_state.json",
            "pipeline.log",
            "evidence_bundle.json",
            "doc_patch.diff",
            "change_summary.md",
            "claims.json",
        ],
    )
    return {
        **state,
        "status": run_state["status"],
        "stage": run_state["stage"],
        "sync_result": sync_result,
        "evidence_bundle": evidence_bundle,
        "release_notes": str(evidence_bundle.get("release_notes", "")),
        "diff_content": str(evidence_bundle.get("diff_content", "")),
        "doc_patch_diff": author_out.doc_patch_diff,
        "change_summary_md": author_out.change_summary_md,
        "claims": author_out.claims,
        "generated_docs": {
            "doc_patch_diff": author_out.doc_patch_diff,
            "change_summary_md": author_out.change_summary_md,
        },
        "artifacts": run_state.get("artifacts", []),
    }


def create_pr_node(state: DocUpdateState) -> DocUpdateState:
    settings = state["settings"]
    store = state["store"]
    context = state["run_context"]
    dry_run = bool(state["dry_run"])
    patch = str(state.get("doc_patch_diff", ""))
    prev_tag = str(state["prev_tag"])
    new_tag = str(state["latest_tag"])

    gate_report = evaluate_quality_gate(
        reviewer_decision="pass",
        blocking_issues=[],
        review_report={"claim_results": []},
        claims=state.get("claims", {}),
        doc_patch_diff=patch,
        path_mapping_file=settings.path_mapping_file,
        quality_gates_file=settings.quality_gates_config_path,
        pre_pr_mode=True,
        artifacts=state.get("artifacts"),
        auto_merge_requested=False,
        idempotency_checked=True,
    )
    if gate_report["decision"] != "pass":
        blocked = store.patch_state(
            context.run_state_path,
            stage="phase6_complete",
            status="failed",
            decision="fail",
            gate_result="failed quality gate",
            pr_result="blocked",
            blocking_issues=gate_report["gate_issues"],
            artifacts=state.get("artifacts", []),
        )
        _log_event(
            store,
            context,
            event="quality_gate_blocked",
            stage="create_pr",
            gate_issues=gate_report["gate_issues"],
        )
        return {
            **state,
            "status": blocked["status"],
            "stage": blocked["stage"],
            "decision": blocked.get("decision"),
            "gate_report": gate_report,
            "review_result": "rejected",
            "blocking_issues": blocked.get("blocking_issues", []),
        }

    if gate_report["no_substantive_change"]:
        done = store.patch_state(
            context.run_state_path,
            stage="phase6_complete",
            status="success",
            decision="pass",
            gate_result="pass",
            pr_result="skipped_no_substantive_change",
            pr_url="",
            blocking_issues=[],
            artifacts=state.get("artifacts", []),
        )
        _log_event(
            store,
            context,
            event="pr_skipped_no_substantive_change",
            stage="create_pr",
        )
        return {
            **state,
            "status": done["status"],
            "stage": done["stage"],
            "decision": done.get("decision"),
            "pr_result": done.get("pr_result", ""),
            "pr_url": "",
            "gate_report": gate_report,
            "review_result": "approved",
            "blocking_issues": [],
        }

    run_state = store.patch_state(context.run_state_path, stage="create_pr", status="running")
    pr_started_at = time.perf_counter()
    _log_event(store, context, event="stage_started", stage="create_pr")
    branch_name = f"docs/auto/{new_tag}-{context.run_id}"
    pr_title = f"docs: sync {prev_tag}..{new_tag}"
    pr_body = _build_pr_body(
        prev_tag=prev_tag,
        new_tag=new_tag,
        change_summary_md=str(state.get("change_summary_md", "")),
    )
    pr_payload = {
        "title": pr_title,
        "base": "main",
        "head": branch_name,
        "body": pr_body,
    }
    pr_payload_path = context.run_dir / "pr_payload.json"
    pr_payload_path.write_text(json.dumps(pr_payload, ensure_ascii=True, indent=2), encoding="utf-8")

    pr_result_obj = create_docs_pr(
        docs_repo_url=settings.matrixorigin_docs_repo,
        docs_repo_dir=settings.docs_repo_dir,
        doc_patch_diff=patch,
        branch_name=branch_name,
        base_branch="main",
        title=pr_title,
        body=pr_body,
        commit_message=f"docs: sync {prev_tag}..{new_tag}",
        dry_run=dry_run,
    )
    if pr_result_obj.get("no_changes", False):
        _log_event(
            store,
            context,
            event="pr_skipped_no_changes_after_apply",
            stage="create_pr",
            elapsed_ms=_elapsed_ms(pr_started_at),
        )
        done = store.patch_state(
            context.run_state_path,
            stage="phase6_complete",
            status="success",
            decision="pass",
            gate_result="pass",
            pr_result="skipped_no_changes_after_apply",
            pr_url="",
            blocking_issues=[],
            artifacts=[
                *state.get("artifacts", []),
                "pr_payload.json",
            ],
        )
        return {
            **state,
            "status": done["status"],
            "stage": done["stage"],
            "decision": done.get("decision"),
            "pr_result": done.get("pr_result", ""),
            "pr_url": "",
            "gate_report": gate_report,
            "review_result": "approved",
        }

    run_state = store.patch_state(
        context.run_state_path,
        stage=run_state["stage"],
        status="running",
        gate_result="pass",
        pr_result=f"created ({pr_result_obj['mode']})",
        pr_url=pr_result_obj.get("pr_url", ""),
        artifacts=[*state.get("artifacts", []), "pr_payload.json"],
    )
    _log_event(
        store,
        context,
        event="stage_finished",
        stage="create_pr",
        elapsed_ms=_elapsed_ms(pr_started_at),
        mode=pr_result_obj.get("mode", ""),
        pr_url=pr_result_obj.get("pr_url", ""),
    )
    return {
        **state,
        "status": run_state["status"],
        "stage": run_state["stage"],
        "pr_result": run_state.get("pr_result", ""),
        "pr_url": run_state.get("pr_url", ""),
        "pr_branch": branch_name,
        "pr_title": pr_title,
        "pr_body": pr_body,
        "pr_payload": pr_payload,
        "gate_report": gate_report,
        "review_result": "changes_requested",
        "artifacts": run_state.get("artifacts", []),
    }


def review_pr_node(state: DocUpdateState) -> DocUpdateState:
    store = state["store"]
    context = state["run_context"]
    router = state["agent_router"]
    dry_run = bool(state["dry_run"])
    settings = state["settings"]

    if not str(state.get("pr_url", "")):
        if not dry_run and str(state.get("pr_result", "")).startswith("created"):
            run_state = store.patch_state(
                context.run_state_path,
                stage="phase6_complete",
                status="failed",
                decision="fail",
                blocking_issues=["created PR result without pr_url in real mode"],
                artifacts=state.get("artifacts", []),
            )
            return {
                **state,
                "status": run_state["status"],
                "stage": run_state["stage"],
                "decision": run_state.get("decision"),
                "review_result": "rejected",
                "blocking_issues": run_state.get("blocking_issues", []),
            }
        return {
            **state,
            "review_result": "approved",
            "review_comments": "",
        }

    run_state = store.patch_state(context.run_state_path, stage="reviewer_agent", status="running")
    reviewer_started_at = time.perf_counter()
    _log_event(store, context, event="stage_started", stage="reviewer_agent")
    pr_context = get_pr_context(pr_url=str(state["pr_url"]), dry_run=dry_run, docs_repo_dir=state["settings"].docs_repo_dir)
    reviewer_out = router.run_reviewer(
        ReviewerAgentInput(
            doc_patch_diff=str(state.get("doc_patch_diff", "")),
            claims=state.get("claims", {}),
            evidence_bundle=state.get("evidence_bundle", {}),
            pr_url=str(state["pr_url"]),
            pr_context=pr_context,
        )
    )
    reviewer_decision = "pass" if reviewer_out.decision == "approved" else "fail"
    gate_report = evaluate_quality_gate(
        reviewer_decision=reviewer_decision,
        blocking_issues=reviewer_out.blocking_issues,
        review_report=reviewer_out.review_report,
        claims=state.get("claims", {}),
        doc_patch_diff=str(state.get("doc_patch_diff", "")),
        path_mapping_file=settings.path_mapping_file,
        quality_gates_file=settings.quality_gates_config_path,
        pre_pr_mode=False,
        artifacts=state.get("artifacts"),
        auto_merge_requested=False,
        idempotency_checked=True,
    )
    review_report_path = context.run_dir / "review_report.json"
    review_report_path.write_text(
        json.dumps(reviewer_out.review_report, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    review_result = "approved" if gate_report["decision"] == "pass" else "changes_requested"
    combined_blocking = [*reviewer_out.blocking_issues, *gate_report["gate_issues"]]
    retry_count = int(state.get("retry_count", 0))
    max_retry = int(state.get("max_retry_count", 2))
    if review_result == "changes_requested" and retry_count >= max_retry:
        review_result = "rejected"
        combined_blocking.append("review loop exceeded max retries")

    status_value = "failed" if review_result == "rejected" else "running"
    decision_value = "fail" if review_result == "rejected" else state.get("decision")
    stage_value = "phase6_complete" if review_result == "rejected" else run_state["stage"]
    run_state = store.patch_state(
        context.run_state_path,
        stage=stage_value,
        status=status_value,
        decision=decision_value,
        reviewer_result=f"wrote {review_report_path.name}",
        gate_result=gate_report["decision"],
        blocking_issues=combined_blocking,
        artifacts=[*state.get("artifacts", []), "review_report.json"],
    )
    _log_event(
        store,
        context,
        event="stage_finished",
        stage="reviewer_agent",
        elapsed_ms=_elapsed_ms(reviewer_started_at),
        review_result=review_result,
        retry_count=retry_count,
        max_retry=max_retry,
        blocking_issue_count=len(combined_blocking),
    )
    return {
        **state,
        "status": run_state["status"],
        "stage": run_state["stage"],
        "review_result": review_result,
        "review_comments": reviewer_out.comments,
        "review_report": reviewer_out.review_report,
        "blocking_issues": combined_blocking,
        "gate_report": gate_report,
        "artifacts": run_state.get("artifacts", []),
    }


def revise_docs_node(state: DocUpdateState) -> DocUpdateState:
    store = state["store"]
    context = state["run_context"]
    router = state["agent_router"]
    dry_run = bool(state["dry_run"])
    settings = state["settings"]

    run_state = store.patch_state(context.run_state_path, stage="revise_docs", status="running")
    revise_started_at = time.perf_counter()
    _log_event(
        store,
        context,
        event="stage_started",
        stage="revise_docs",
        attempt=int(state.get("retry_count", 0)) + 1,
    )
    feedback = str(state.get("review_comments", ""))
    author_out = router.run_author(
        AuthorAgentInput(
            prev_tag=str(state["prev_tag"]),
            new_tag=str(state["latest_tag"]),
            evidence_bundle=state.get("evidence_bundle", {}),
            release_notes=str(
                state.get("release_notes", state.get("evidence_bundle", {}).get("release_notes", ""))
            ),
            diff_content=str(
                state.get("diff_content", state.get("evidence_bundle", {}).get("diff_content", ""))
            ),
            review_feedback=feedback,
        )
    )
    doc_patch_path = context.run_dir / "doc_patch.diff"
    change_summary_path = context.run_dir / "change_summary.md"
    claims_path = context.run_dir / "claims.json"
    doc_patch_path.write_text(author_out.doc_patch_diff, encoding="utf-8")
    change_summary_path.write_text(author_out.change_summary_md, encoding="utf-8")
    claims_path.write_text(json.dumps(author_out.claims, ensure_ascii=True, indent=2), encoding="utf-8")

    update_docs_pr_branch(
        docs_repo_url=settings.matrixorigin_docs_repo,
        docs_repo_dir=settings.docs_repo_dir,
        branch_name=str(state.get("pr_branch", "")),
        doc_patch_diff=author_out.doc_patch_diff,
        commit_message=f"docs: revise {state['latest_tag']} (attempt {int(state.get('retry_count', 0)) + 1})",
        dry_run=dry_run,
    )
    _log_event(
        store,
        context,
        event="stage_finished",
        stage="revise_docs",
        elapsed_ms=_elapsed_ms(revise_started_at),
        next_retry_count=int(state.get("retry_count", 0)) + 1,
        patch_size_chars=len(author_out.doc_patch_diff),
    )
    return {
        **state,
        "status": run_state["status"],
        "stage": run_state["stage"],
        "doc_patch_diff": author_out.doc_patch_diff,
        "change_summary_md": author_out.change_summary_md,
        "claims": author_out.claims,
        "retry_count": int(state.get("retry_count", 0)) + 1,
    }


def approve_pr_node(state: DocUpdateState) -> DocUpdateState:
    store = state["store"]
    context = state["run_context"]
    dry_run = bool(state["dry_run"])

    if str(state.get("pr_url", "")):
        approve_pr(pr_url=str(state["pr_url"]), dry_run=dry_run)

    run_state = store.patch_state(
        context.run_state_path,
        stage="phase6_complete",
        status="success",
        decision="pass",
        blocking_issues=[],
        artifacts=state.get("artifacts", []),
    )
    _log_event(
        store,
        context,
        event="run_completed",
        stage="phase6_complete",
        status="success",
        decision="pass",
        pr_url=str(state.get("pr_url", "")),
    )
    return {
        **state,
        "status": run_state["status"],
        "stage": run_state["stage"],
        "decision": run_state.get("decision"),
        "review_result": "approved",
        "blocking_issues": [],
    }


def _fetch_route(state: DocUpdateState) -> str:
    return "skipped" if state.get("status") == "skipped" else "continue"


def _create_pr_route(state: DocUpdateState) -> str:
    result = str(state.get("pr_result", ""))
    if result.startswith("skipped") or result == "blocked" or state.get("status") == "failed":
        return "skip_review"
    return "to_review"


def _review_route(state: DocUpdateState) -> str:
    result = str(state.get("review_result", "changes_requested"))
    if result == "approved":
        return "approved"
    if result == "changes_requested":
        return "changes_requested"
    return "rejected"


def _build_pr_body(*, prev_tag: str, new_tag: str, change_summary_md: str) -> str:
    lines = [
        f"## Summary ({prev_tag} -> {new_tag})",
        "",
        change_summary_md.strip(),
        "",
        "## Audit",
        "- evidence, claims and review report are attached in workflow artifacts",
        "",
    ]
    return "\n".join(lines)


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def _log_event(store, context, *, event: str, stage: str, **fields) -> None:
    payload = {"event": event, "stage": stage, **fields}
    store.append_log(context.pipeline_log_path, json.dumps(payload, ensure_ascii=True))
