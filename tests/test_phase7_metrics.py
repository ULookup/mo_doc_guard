from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

from app.core.phase7_metrics import (
    append_metrics_history,
    build_run_metrics,
    classify_blocking_issues,
    load_metrics_history,
    summarize_metrics_history,
)


def test_classify_blocking_issues() -> None:
    categories = classify_blocking_issues(
        [
            "evidence code_path missing",
            "docs_path not mapped",
            "forbidden AI marker detected",
            "G4: quality gate failed",
            "unexpected error",
        ]
    )
    assert categories["evidence"] == 1
    assert categories["mapping"] == 1
    assert categories["ai_pollution"] == 1
    assert categories["quality_gate"] == 1
    assert categories["other"] == 1


def test_build_and_summarize_metrics(tmp_path: Path) -> None:
    started = datetime.now(UTC)
    ended = started + timedelta(seconds=12)
    metrics = build_run_metrics(
        state={
            "run_id": "run-1",
            "idempotency_key": "v1..v2",
            "status": "success",
            "decision": "pass",
            "stage": "phase6_complete",
            "pr_result": "created (dry_run)",
            "blocking_issues": [],
        },
        started_at=started,
        ended_at=ended,
    )
    assert metrics["duration_seconds"] >= 12
    append_metrics_history(tmp_path, metrics)
    records = load_metrics_history(tmp_path)
    assert len(records) == 1
    summary = summarize_metrics_history(records)
    assert summary["total_runs"] == 1
    assert summary["success_rate"] == 1.0
    assert summary["pr_create_rate"] == 1.0


def test_load_metrics_history_ignores_empty_lines(tmp_path: Path) -> None:
    history = tmp_path / "metrics_history.jsonl"
    history.write_text(json.dumps({"run_id": "r1"}) + "\nnot-json\n", encoding="utf-8")
    records = load_metrics_history(tmp_path)
    assert len(records) == 1


def test_failure_categories_only_count_failed_runs() -> None:
    summary = summarize_metrics_history(
        [
            {
                "status": "success",
                "blocking_issue_categories": {"mapping": 3},
            },
            {
                "status": "failed",
                "blocking_issue_categories": {"mapping": 1, "evidence": 2},
            },
        ]
    )
    assert summary["top_failure_categories"]["mapping"] == 1
    assert summary["top_failure_categories"]["evidence"] == 2
