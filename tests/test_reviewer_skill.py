from __future__ import annotations

from app.skills.mo_doc_reviewer import ReviewerInput, run_reviewer_skill


def test_reviewer_passes_when_claims_are_verifiable() -> None:
    output = run_reviewer_skill(
        ReviewerInput(
            doc_patch_diff=(
                "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/sql-syntax.md\n"
                "--- a/docs/sql-reference/sql-syntax.md\n"
                "+++ b/docs/sql-reference/sql-syntax.md\n"
                "@@ -1 +1 @@\n"
                "+Update notes.\n"
            ),
            claims={
                "claim_count": 1,
                "claims": [
                    {
                        "claim_id": "C001",
                        "docs_path": "docs/sql-reference/sql-syntax.md",
                        "evidence": {"code_path": "pkg/sql/parsers/parser.go"},
                    }
                ],
            },
            evidence_bundle={
                "retrieval_scope": [
                    {
                        "code_path": "pkg/sql/parsers/parser.go",
                        "in_scope": True,
                        "mapped_docs": [
                            {"docs_path": "docs/sql-reference/sql-syntax.md"},
                        ],
                    }
                ]
            },
        )
    )
    assert output.decision == "pass"
    assert output.blocking_issues == []


def test_reviewer_fails_when_docs_path_not_in_patch() -> None:
    output = run_reviewer_skill(
        ReviewerInput(
            doc_patch_diff="",
            claims={
                "claim_count": 1,
                "claims": [
                    {
                        "claim_id": "C001",
                        "docs_path": "docs/sql-reference/sql-syntax.md",
                        "evidence": {"code_path": "pkg/sql/parsers/parser.go"},
                    }
                ],
            },
            evidence_bundle={
                "retrieval_scope": [
                    {"code_path": "pkg/sql/parsers/parser.go", "in_scope": True, "mapped_docs": []}
                ]
            },
        )
    )
    assert output.decision == "fail"
    assert len(output.blocking_issues) >= 1


def test_reviewer_fails_on_forbidden_marker() -> None:
    output = run_reviewer_skill(
        ReviewerInput(
            doc_patch_diff=(
                "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/sql-syntax.md\n"
                "+This section is AI-generated.\n"
            ),
            claims={"claim_count": 0, "claims": []},
            evidence_bundle={"retrieval_scope": []},
        )
    )
    assert output.decision == "fail"
    assert any("forbidden AI marker" in issue for issue in output.blocking_issues)


def test_reviewer_fails_when_docs_mapping_is_mismatched() -> None:
    output = run_reviewer_skill(
        ReviewerInput(
            doc_patch_diff=(
                "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/sql-syntax.md\n"
                "+Update notes.\n"
            ),
            claims={
                "claim_count": 1,
                "claims": [
                    {
                        "claim_id": "C001",
                        "docs_path": "docs/sql-reference/sql-syntax.md",
                        "evidence": {"code_path": "pkg/sql/parsers/parser.go"},
                    }
                ],
            },
            evidence_bundle={
                "retrieval_scope": [
                    {
                        "code_path": "pkg/sql/parsers/parser.go",
                        "in_scope": True,
                        "mapped_docs": [
                            {"docs_path": "docs/sql-reference/system-variables.md"},
                        ],
                    }
                ]
            },
        )
    )
    assert output.decision == "fail"
    assert any("not mapped" in issue for issue in output.blocking_issues)
