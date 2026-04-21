"""Run state and idempotency helpers for file-based execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


RUN_STATE_FILENAME = "run_state.json"
PIPELINE_LOG_FILENAME = "pipeline.log"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def generate_run_id() -> str:
    return f"run-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def build_idempotency_key(prev_tag: str, new_tag: str) -> str:
    return f"{prev_tag}..{new_tag}"


@dataclass(frozen=True)
class RunContext:
    run_id: str
    prev_tag: str
    new_tag: str
    idempotency_key: str
    run_dir: Path
    run_state_path: Path
    pipeline_log_path: Path


def create_run_context(runs_dir: Path, prev_tag: str, new_tag: str) -> RunContext:
    run_id = generate_run_id()
    run_dir = runs_dir / run_id
    return RunContext(
        run_id=run_id,
        prev_tag=prev_tag,
        new_tag=new_tag,
        idempotency_key=build_idempotency_key(prev_tag, new_tag),
        run_dir=run_dir,
        run_state_path=run_dir / RUN_STATE_FILENAME,
        pipeline_log_path=run_dir / PIPELINE_LOG_FILENAME,
    )


class RunStateStore:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir

    def initialize(self, context: RunContext, trigger_source: str, dry_run: bool) -> dict[str, Any]:
        context.run_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "run_id": context.run_id,
            "prev_tag": context.prev_tag,
            "new_tag": context.new_tag,
            "idempotency_key": context.idempotency_key,
            "trigger_source": trigger_source,
            "dry_run": dry_run,
            "stage": "trigger",
            "status": "running",
            "decision": None,
            "artifacts": [RUN_STATE_FILENAME, PIPELINE_LOG_FILENAME],
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        }
        self.write_state(context.run_state_path, state)
        return state

    def append_log(self, log_path: Path, message: str) -> None:
        line = f"{utc_now_iso()} {message}\n"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as file:
            file.write(line)

    def patch_state(self, state_path: Path, **updates: Any) -> dict[str, Any]:
        state = self.read_state(state_path)
        state.update(updates)
        state["updated_at"] = utc_now_iso()
        self.write_state(state_path, state)
        return state

    def has_successful_run(self, idempotency_key: str, include_dry_run: bool) -> bool:
        if not self.runs_dir.exists():
            return False
        for candidate in self.runs_dir.glob("*/run_state.json"):
            try:
                state = self.read_state(candidate)
            except (json.JSONDecodeError, OSError):
                continue
            if state.get("idempotency_key") != idempotency_key:
                continue
            if state.get("status") == "success":
                if not include_dry_run and state.get("dry_run", False):
                    continue
                return True
        return False

    @staticmethod
    def read_state(state_path: Path) -> dict[str, Any]:
        with state_path.open("r", encoding="utf-8") as file:
            return json.load(file)

    @staticmethod
    def write_state(state_path: Path, state: dict[str, Any]) -> None:
        with state_path.open("w", encoding="utf-8") as file:
            json.dump(state, file, ensure_ascii=True, indent=2)
