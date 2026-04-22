"""Workflow entrypoint backed by LangGraph dual-agent orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
import argparse
import json
import logging
import os
from pathlib import Path
import time
import sys
from typing import Any, TypedDict

from app.agents.registry import AgentRegistry
from app.agents.router import AgentRouter
from app.core.phase7_metrics import append_metrics_history, build_run_metrics
from app.core.run_state import RunStateStore
from app.core.settings import load_settings
from app.graph.langgraph_workflow import build_langgraph_app

logger = logging.getLogger(__name__)


class PipelineState(TypedDict, total=False):
    run_id: str
    idempotency_key: str
    prev_tag: str
    new_tag: str
    trigger_source: str
    stage: str
    status: str
    decision: str | None
    dry_run: bool
    sync_result: str
    evidence_result: str
    writer_result: str
    reviewer_result: str
    gate_result: str
    pr_result: str
    pr_url: str
    blocking_issues: list[str]
    error: str


def planned_nodes() -> list[str]:
    """Return planned node sequence from plan.md."""
    return [
        "trigger",
        "fetch_changes",
        "analyze_and_generate",
        "create_pr",
        "review_pr",
        "revise_docs",
        "approve_pr",
    ]


def run_phase6(
    prev_tag: str | None,
    new_tag: str,
    trigger_source: str,
    dry_run: bool,
) -> PipelineState:
    attempts = _env_int("WORKFLOW_RETRIES", 2, minimum=1)
    backoff_seconds = _env_float("WORKFLOW_RETRY_BACKOFF_SECONDS", 2.0, minimum=0.0)
    logger.info(
        "workflow.start prev_tag=%s new_tag=%s dry_run=%s attempts=%s",
        prev_tag,
        new_tag,
        dry_run,
        attempts,
    )
    for attempt in range(1, attempts + 1):
        logger.info("workflow.attempt.started attempt=%s/%s", attempt, attempts)
        settings = load_settings()
        settings.runs_dir.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now(UTC)
        store = RunStateStore(settings.runs_dir)
        app = build_langgraph_app()
        registry = AgentRegistry(
            agents_config_path=settings.agents_config_path,
            prompts_config_path=settings.prompts_config_path,
            model_router=settings.model_router,
            path_mapping_file=settings.path_mapping_file,
        )
        router = AgentRouter(registry)
        try:
            final_graph_state = app.invoke(
                {
                    "latest_tag": new_tag,
                    "prev_tag": prev_tag or "",
                    "trigger_source": trigger_source,
                    "dry_run": dry_run,
                    "settings": settings,
                    "store": store,
                    "agent_router": router,
                    "started_at": started_at,
                    "max_retry_count": router.max_revision_loops,
                }
            )
            context = final_graph_state.get("run_context")
            if context is not None:
                run_state = store.read_state(context.run_state_path)
                _persist_phase7_metrics(context, store, run_state, settings.runs_dir, started_at)
                logger.info(
                    "workflow.attempt.finished attempt=%s/%s status=%s stage=%s run_id=%s",
                    attempt,
                    attempts,
                    run_state.get("status"),
                    run_state.get("stage"),
                    run_state.get("run_id"),
                )
                return _state_view(run_state, dry_run=dry_run)
            logger.info("workflow.attempt.finished attempt=%s/%s state=graph_without_context", attempt, attempts)
            return PipelineState(
                run_id=str(final_graph_state.get("run_id", "")),
                idempotency_key=str(final_graph_state.get("idempotency_key", "")),
                prev_tag=str(final_graph_state.get("prev_tag", "")),
                new_tag=str(final_graph_state.get("latest_tag", new_tag)),
                trigger_source=trigger_source,
                stage=str(final_graph_state.get("stage", "bootstrap")),
                status=str(final_graph_state.get("status", "failed")),
                decision=str(final_graph_state.get("decision", "fail")),
                dry_run=dry_run,
                sync_result=str(final_graph_state.get("sync_result", "")),
                evidence_result=str(final_graph_state.get("evidence_result", "")),
                writer_result=str(final_graph_state.get("writer_result", "")),
                reviewer_result=str(final_graph_state.get("reviewer_result", "")),
                gate_result=str(final_graph_state.get("gate_result", "")),
                pr_result=str(final_graph_state.get("pr_result", "")),
                pr_url=str(final_graph_state.get("pr_url", "")),
                blocking_issues=final_graph_state.get("blocking_issues", []),
                error=str(final_graph_state.get("error", "")),
            )
        except Exception as exc:  # noqa: BLE001
            retryable = _is_retryable_error(str(exc))
            logger.warning(
                "workflow.attempt.failed attempt=%s/%s retryable=%s error=%s",
                attempt,
                attempts,
                retryable,
                str(exc),
            )
            if attempt < attempts and retryable:
                time.sleep(backoff_seconds * attempt)
                continue
            bootstrap_state = PipelineState(
                run_id=f"bootstrap-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
                idempotency_key="",
                prev_tag=prev_tag or "",
                new_tag=new_tag,
                trigger_source=trigger_source,
                stage="bootstrap",
                status="failed",
                decision="fail",
                dry_run=dry_run,
                sync_result="",
                evidence_result="",
                writer_result="",
                reviewer_result="",
                gate_result="",
                pr_result="",
                pr_url="",
                blocking_issues=[],
                error=str(exc),
            )
            _persist_bootstrap_failure_metrics(
                state=bootstrap_state,
                runs_dir=settings.runs_dir,
                started_at=started_at,
            )
            return bootstrap_state
    raise RuntimeError("workflow retries exhausted unexpectedly")


def run_phase3(
    prev_tag: str | None,
    new_tag: str,
    trigger_source: str,
    dry_run: bool,
) -> PipelineState:
    """Backward-compatible wrapper for earlier callers."""
    return run_phase6(
        prev_tag=prev_tag,
        new_tag=new_tag,
        trigger_source=trigger_source,
        dry_run=dry_run,
    )


def run_phase2(prev_tag: str, new_tag: str, trigger_source: str, dry_run: bool) -> PipelineState:
    """Backward-compatible wrapper for earlier tests/callers."""
    return run_phase6(
        prev_tag=prev_tag,
        new_tag=new_tag,
        trigger_source=trigger_source,
        dry_run=dry_run,
    )


def _state_view(state: dict[str, Any], dry_run: bool) -> PipelineState:
    return PipelineState(
        run_id=state["run_id"],
        idempotency_key=state["idempotency_key"],
        prev_tag=state["prev_tag"],
        new_tag=state["new_tag"],
        trigger_source=state["trigger_source"],
        stage=state["stage"],
        status=state["status"],
        decision=state.get("decision"),
        dry_run=state.get("dry_run", dry_run),
        sync_result=state.get("sync_result", ""),
        evidence_result=state.get("evidence_result", ""),
        writer_result=state.get("writer_result", ""),
        reviewer_result=state.get("reviewer_result", ""),
        gate_result=state.get("gate_result", ""),
        pr_result=state.get("pr_result", ""),
        pr_url=state.get("pr_url", ""),
        blocking_issues=state.get("blocking_issues", []),
        error=state.get("error", ""),
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 6 pipeline")
    parser.add_argument("--prev-tag", required=False, default="", help="Previous tag")
    parser.add_argument("--new-tag", required=True, help="New tag")
    parser.add_argument(
        "--trigger-source",
        default="manual",
        choices=["manual", "tag", "workflow_dispatch"],
        help="Source of pipeline trigger",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run without mutating external repositories",
    )
    return parser.parse_args()


def _persist_phase7_metrics(
    context: Any,
    store: RunStateStore,
    state: dict[str, Any],
    runs_dir: Path,
    started_at: datetime,
) -> None:
    if context is None:
        return
    try:
        metrics = build_run_metrics(
            state=state,
            started_at=started_at,
            ended_at=datetime.now(UTC),
        )
        metrics_path = context.run_dir / "run_metrics.json"
        metrics_path.write_text(json.dumps(metrics, ensure_ascii=True, indent=2), encoding="utf-8")
        append_metrics_history(runs_dir, metrics)

        artifacts = state.get("artifacts", [])
        if isinstance(artifacts, list) and "run_metrics.json" not in artifacts:
            updated_artifacts = [*artifacts, "run_metrics.json"]
            store.patch_state(context.run_state_path, artifacts=updated_artifacts)
    except Exception:  # noqa: BLE001
        return


def _persist_bootstrap_failure_metrics(
    *,
    state: dict[str, Any],
    runs_dir: Path,
    started_at: datetime,
) -> None:
    try:
        metrics = build_run_metrics(
            state=state,
            started_at=started_at,
            ended_at=datetime.now(UTC),
        )
        append_metrics_history(runs_dir, metrics)
    except Exception:  # noqa: BLE001
        return


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args()
    result = run_phase6(
        prev_tag=args.prev_tag or None,
        new_tag=args.new_tag,
        trigger_source=args.trigger_source,
        dry_run=args.dry_run,
    )
    print(result)
    if result["status"] == "failed":
        sys.exit(1)


def _is_retryable_error(message: str) -> bool:
    lowered = message.lower()
    retry_markers = [
        "timed out",
        "couldn't connect",
        "failed to connect",
        "connection reset",
        "rpc failed",
        "curl 28",
        "http2 framing layer",
        "bad gateway",
        "502",
    ]
    return any(marker in lowered for marker in retry_markers)


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


if __name__ == "__main__":
    main()
