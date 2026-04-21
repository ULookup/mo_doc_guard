"""Phase 7 observability helpers for run metrics and reports."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any


METRICS_HISTORY_FILE = "metrics_history.jsonl"


def classify_blocking_issues(issues: list[str]) -> dict[str, int]:
    categories = {
        "evidence": 0,
        "mapping": 0,
        "ai_pollution": 0,
        "quality_gate": 0,
        "other": 0,
    }
    for issue in issues:
        lowered = issue.lower()
        if "evidence" in lowered:
            categories["evidence"] += 1
        elif "mapped" in lowered or "docs_path" in lowered or "whitelist" in lowered:
            categories["mapping"] += 1
        elif "ai marker" in lowered or "forbidden ai" in lowered:
            categories["ai_pollution"] += 1
        elif "g" in lowered and "quality gate" in lowered:
            categories["quality_gate"] += 1
        else:
            categories["other"] += 1
    return categories


def build_run_metrics(
    state: dict[str, Any],
    started_at: datetime,
    ended_at: datetime,
) -> dict[str, Any]:
    duration_seconds = max(0.0, (ended_at - started_at).total_seconds())
    blocking_issues = state.get("blocking_issues", [])
    if not isinstance(blocking_issues, list):
        blocking_issues = []
    pr_result = str(state.get("pr_result", ""))
    return {
        "run_id": state.get("run_id", ""),
        "idempotency_key": state.get("idempotency_key", ""),
        "status": state.get("status", "unknown"),
        "decision": state.get("decision"),
        "stage": state.get("stage", ""),
        "duration_seconds": duration_seconds,
        "pr_result": pr_result,
        "pr_created": pr_result.startswith("created"),
        "blocking_issue_count": len(blocking_issues),
        "blocking_issue_categories": classify_blocking_issues([str(i) for i in blocking_issues]),
        "token_cost_estimate": None,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def append_metrics_history(runs_dir: Path, metrics: dict[str, Any]) -> Path:
    history_path = runs_dir / METRICS_HISTORY_FILE
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(metrics, ensure_ascii=True) + "\n")
    return history_path


def summarize_metrics_history(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    if total == 0:
        return {
            "total_runs": 0,
            "success_rate": 0.0,
            "pr_create_rate": 0.0,
            "avg_duration_seconds": 0.0,
            "top_failure_categories": {},
        }

    success = sum(1 for item in records if item.get("status") == "success")
    pr_created = sum(1 for item in records if item.get("pr_created") is True)
    durations = [float(item.get("duration_seconds", 0.0)) for item in records]
    category_counts: dict[str, int] = {}
    failed_records = [item for item in records if item.get("status") != "success"]
    for item in failed_records:
        categories = item.get("blocking_issue_categories", {})
        if not isinstance(categories, dict):
            continue
        for key, value in categories.items():
            category_counts[key] = category_counts.get(key, 0) + int(value)

    sorted_categories = dict(
        sorted(category_counts.items(), key=lambda pair: pair[1], reverse=True)
    )
    return {
        "total_runs": total,
        "success_rate": round(success / total, 4),
        "pr_create_rate": round(pr_created / total, 4),
        "avg_duration_seconds": round(sum(durations) / total, 3),
        "top_failure_categories": sorted_categories,
    }


def load_metrics_history(runs_dir: Path) -> list[dict[str, Any]]:
    history_path = runs_dir / METRICS_HISTORY_FILE
    if not history_path.exists():
        return []
    records: list[dict[str, Any]] = []
    with history_path.open("r", encoding="utf-8") as file:
        for line in file:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue
    return records
