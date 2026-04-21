from __future__ import annotations

from pathlib import Path

from app.core.quality_gate import evaluate_quality_gate


def test_quality_gate_passes_with_verified_claims() -> None:
    gate = evaluate_quality_gate(
        reviewer_decision="pass",
        blocking_issues=[],
        review_report={"claim_results": [{"status": "pass"}]},
        claims={
            "claim_count": 1,
            "claims": [
                {
                    "evidence": {
                        "code_path": "pkg/sql/parsers/parser.go",
                        "reason": "parser behavior changed",
                    }
                }
            ],
        },
        doc_patch_diff=(
            "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/sql-syntax.md\n"
            "+Update notes.\n"
        ),
        path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
    )
    assert gate["decision"] == "pass"
    assert gate["no_substantive_change"] is False


def test_quality_gate_fails_for_unverified_claims() -> None:
    gate = evaluate_quality_gate(
        reviewer_decision="pass",
        blocking_issues=[],
        review_report={"claim_results": [{"status": "fail"}]},
        claims={
            "claim_count": 1,
            "claims": [
                {
                    "evidence": {
                        "code_path": "pkg/sql/parsers/parser.go",
                        "reason": "parser behavior changed",
                    }
                }
            ],
        },
        doc_patch_diff=(
            "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/sql-syntax.md\n"
            "+Update notes.\n"
        ),
        path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
    )
    assert gate["decision"] == "fail"


def test_quality_gate_marks_empty_patch_as_no_substantive_change() -> None:
    gate = evaluate_quality_gate(
        reviewer_decision="pass",
        blocking_issues=[],
        review_report={"claim_results": []},
        claims={"claim_count": 0},
        doc_patch_diff="",
        path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
    )
    assert gate["decision"] == "pass"
    assert gate["no_substantive_change"] is True


def test_quality_gate_fails_without_claim_provenance() -> None:
    gate = evaluate_quality_gate(
        reviewer_decision="pass",
        blocking_issues=[],
        review_report={"claim_results": [{"status": "pass"}]},
        claims={"claim_count": 1, "claims": [{"evidence": {"code_path": "", "reason": ""}}]},
        doc_patch_diff=(
            "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/sql-syntax.md\n"
            "+Update notes.\n"
        ),
        path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
    )
    assert gate["decision"] == "fail"


def test_quality_gate_pre_pr_mode_skips_reviewer_checks() -> None:
    gate = evaluate_quality_gate(
        reviewer_decision="fail",
        blocking_issues=["review failed"],
        review_report={"claim_results": [{"status": "fail"}]},
        claims={
            "claim_count": 1,
            "claims": [
                {
                    "evidence": {
                        "code_path": "pkg/sql/parsers/parser.go",
                        "reason": "parser behavior changed",
                    }
                }
            ],
        },
        doc_patch_diff=(
            "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/sql-syntax.md\n"
            "+Update notes.\n"
        ),
        path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
        pre_pr_mode=True,
    )
    assert gate["decision"] == "pass"


def test_quality_gate_honors_configured_gate_ids(tmp_path: Path) -> None:
    gate_config = tmp_path / "quality_gates.yaml"
    gate_config.write_text(
        "\n".join(
            [
                "gates:",
                "  - id: G4",
                "    level: blocker",
            ]
        ),
        encoding="utf-8",
    )
    gate = evaluate_quality_gate(
        reviewer_decision="fail",
        blocking_issues=["review failed"],
        review_report={"claim_results": [{"status": "fail"}]},
        claims={"claim_count": 1, "claims": [{"evidence": {"code_path": "", "reason": ""}}]},
        doc_patch_diff=(
            "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/sql-syntax.md\n"
            "+Update notes.\n"
        ),
        path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
        quality_gates_file=gate_config,
    )
    assert gate["decision"] == "pass"


def test_quality_gate_fails_for_non_empty_patch_without_git_header() -> None:
    gate = evaluate_quality_gate(
        reviewer_decision="pass",
        blocking_issues=[],
        review_report={"claim_results": []},
        claims={"claim_count": 0},
        doc_patch_diff="+Update without git diff header\n",
        path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
    )
    assert gate["decision"] == "fail"


def test_quality_gate_fails_for_mismatched_a_b_paths() -> None:
    gate = evaluate_quality_gate(
        reviewer_decision="pass",
        blocking_issues=[],
        review_report={"claim_results": []},
        claims={"claim_count": 0},
        doc_patch_diff=(
            "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/system-variables.md\n"
            "+Update notes.\n"
        ),
        path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
    )
    assert gate["decision"] == "fail"


def test_quality_gate_fails_for_garbage_line_outside_diff_blocks() -> None:
    gate = evaluate_quality_gate(
        reviewer_decision="pass",
        blocking_issues=[],
        review_report={"claim_results": []},
        claims={"claim_count": 0},
        doc_patch_diff=(
            "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/sql-syntax.md\n"
            "@@ -1 +1 @@\n"
            "+Update notes.\n"
            "THIS_IS_NOT_A_VALID_DIFF_LINE\n"
        ),
        path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
    )
    assert gate["decision"] == "fail"
