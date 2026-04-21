"""Quality gate evaluation for Phase 6."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.retrieval.incremental_scope import load_path_mappings


def evaluate_quality_gate(
    *,
    reviewer_decision: str,
    blocking_issues: list[str],
    review_report: dict[str, Any],
    claims: dict[str, Any],
    doc_patch_diff: str,
    path_mapping_file: Path,
    quality_gates_file: Path | None = None,
    pre_pr_mode: bool = False,
    artifacts: list[str] | None = None,
    auto_merge_requested: bool = False,
    idempotency_checked: bool = True,
) -> dict[str, Any]:
    gate_issues: list[str] = []
    enabled_gates = _load_enabled_gates(quality_gates_file)

    if "G3" in enabled_gates and not pre_pr_mode and reviewer_decision != "pass":
        gate_issues.append("G3: reviewer decision is not pass")
    if "G3" in enabled_gates and not pre_pr_mode and blocking_issues:
        gate_issues.append("G3: blocking issues are not empty")
    if "G2" in enabled_gates and not pre_pr_mode and not _all_claims_verified(review_report, claims):
        gate_issues.append("G2: not all claims are verified as pass")
    if "G1" in enabled_gates and not _claims_have_provenance(claims):
        gate_issues.append("G1: claims must include evidence provenance")
    if "G4" in enabled_gates and not _patch_paths_in_whitelist(doc_patch_diff, path_mapping_file):
        gate_issues.append("G4: doc patch path outside whitelist")
    if "G5" in enabled_gates and not _has_required_artifacts(artifacts):
        gate_issues.append("G5: missing required audit artifacts")
    if "G6" in enabled_gates and auto_merge_requested:
        gate_issues.append("G6: auto merge is not allowed")
    if "G8" in enabled_gates and not idempotency_checked:
        gate_issues.append("G8: idempotency check not completed")

    no_substantive_change = _is_empty_patch(doc_patch_diff) if "G7" in enabled_gates else False
    return {
        "decision": "pass" if not gate_issues else "fail",
        "gate_issues": gate_issues,
        "no_substantive_change": no_substantive_change,
    }


def _all_claims_verified(review_report: dict[str, Any], claims: dict[str, Any]) -> bool:
    expected_count = int(claims.get("claim_count", 0))
    claim_results = review_report.get("claim_results", [])
    if not isinstance(claim_results, list):
        return False
    if len(claim_results) != expected_count:
        return False
    return all(isinstance(item, dict) and item.get("status") == "pass" for item in claim_results)


def _patch_paths_in_whitelist(doc_patch_diff: str, path_mapping_file: Path) -> bool:
    allowed_paths = {
        str(item.get("docs_path", ""))
        for item in load_path_mappings(path_mapping_file)
        if str(item.get("docs_path", ""))
    }
    if not doc_patch_diff.strip():
        return True

    header_count = 0
    in_file_block = False
    for line in doc_patch_diff.splitlines():
        if line == "":
            continue
        if not line.startswith("diff --git "):
            if line.startswith(("--- ", "+++ ", "@@", "+", "-", " ")):
                if not in_file_block:
                    return False
                continue
            return False
        header_count += 1
        in_file_block = True
        parts = line.split()
        if len(parts) < 4 or not parts[2].startswith("a/") or not parts[3].startswith("b/"):
            return False
        a_path = parts[2][2:]
        b_path = parts[3][2:]
        if a_path != b_path:
            return False
        if a_path not in allowed_paths:
            return False
    return header_count > 0


def _claims_have_provenance(claims: dict[str, Any]) -> bool:
    expected_count = int(claims.get("claim_count", 0))
    if expected_count == 0:
        return True
    entries = claims.get("claims", [])
    if not isinstance(entries, list) or len(entries) != expected_count:
        return False
    for claim in entries:
        if not isinstance(claim, dict):
            return False
        evidence = claim.get("evidence", {})
        if not isinstance(evidence, dict):
            return False
        code_path = str(evidence.get("code_path", "")).strip()
        reason = str(evidence.get("reason", "")).strip()
        if not code_path or not reason:
            return False
    return True


def _is_empty_patch(doc_patch_diff: str) -> bool:
    return doc_patch_diff.strip() == ""


def _has_required_artifacts(artifacts: list[str] | None) -> bool:
    if artifacts is None:
        return True
    required = {"run_state.json", "pipeline.log", "evidence_bundle.json", "claims.json"}
    return required.issubset(set(artifacts))


def _load_enabled_gates(quality_gates_file: Path | None) -> set[str]:
    if quality_gates_file is None or not quality_gates_file.exists():
        return {"G1", "G2", "G3", "G4", "G7"}
    with quality_gates_file.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    gates = data.get("gates", []) if isinstance(data, dict) else []
    enabled: set[str] = set()
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, dict):
                continue
            gate_id = str(gate.get("id", "")).strip()
            if gate_id:
                enabled.add(gate_id)
    return enabled or {"G1", "G2", "G3", "G4", "G7"}
