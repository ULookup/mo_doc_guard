#!/usr/bin/env python3
"""Generate Phase 7 rollout report from metrics history."""

from __future__ import annotations

import json

from app.core.phase7_metrics import load_metrics_history, summarize_metrics_history
from app.core.settings import load_settings


def main() -> None:
    settings = load_settings()
    records = load_metrics_history(settings.runs_dir)
    summary = summarize_metrics_history(records)
    output_path = settings.runs_dir / "phase7_report.json"
    output_path.write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
