from __future__ import annotations

from pathlib import Path

import pytest

from app.skills.mo_doc_writer import WriterInput, run_writer_skill


def test_writer_generates_claims_and_summary() -> None:
    output = run_writer_skill(
        WriterInput(
            prev_tag="v1.0.0",
            new_tag="v1.1.0",
            evidence_bundle={
                "retrieval_scope": [
                    {
                        "code_path": "pkg/sql/parsers/parser.go",
                        "mapped_docs": [
                            {
                                "topic": "sql_syntax",
                                "docs_path": "docs/sql-reference/sql-syntax.md",
                            }
                        ],
                        "in_scope": True,
                    }
                ]
            },
            path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
        )
    )
    assert output.claims["claim_count"] == 1
    assert "docs/sql-reference/sql-syntax.md" in output.doc_patch_diff
    assert "Proposed Documentation Updates" in output.change_summary_md


def test_writer_claim_ids_are_unique_for_multiple_mappings() -> None:
    output = run_writer_skill(
        WriterInput(
            prev_tag="v1.0.0",
            new_tag="v1.1.0",
            evidence_bundle={
                "retrieval_scope": [
                    {
                        "code_path": "pkg/sql/parsers/parser.go",
                        "mapped_docs": [
                            {
                                "topic": "sql_syntax",
                                "docs_path": "docs/sql-reference/sql-syntax.md",
                            },
                            {
                                "topic": "system_variables",
                                "docs_path": "docs/sql-reference/system-variables.md",
                            },
                        ],
                        "in_scope": True,
                    }
                ]
            },
            path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
        )
    )
    claim_ids = [claim["claim_id"] for claim in output.claims["claims"]]
    assert len(claim_ids) == len(set(claim_ids))


def test_writer_rejects_non_whitelist_path() -> None:
    with pytest.raises(ValueError, match="outside whitelist"):
        run_writer_skill(
            WriterInput(
                prev_tag="v1.0.0",
                new_tag="v1.1.0",
                evidence_bundle={
                    "retrieval_scope": [
                        {
                            "code_path": "pkg/sql/parsers/parser.go",
                            "mapped_docs": [
                                {
                                    "topic": "sql_syntax",
                                    "docs_path": "docs/forbidden/other.md",
                                }
                            ],
                            "in_scope": True,
                        }
                    ]
                },
                path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
            )
        )


def test_writer_rejects_invalid_retrieval_scope_type() -> None:
    with pytest.raises(ValueError, match="retrieval_scope"):
        run_writer_skill(
            WriterInput(
                prev_tag="v1.0.0",
                new_tag="v1.1.0",
                evidence_bundle={"retrieval_scope": "invalid"},
                path_mapping_file=Path("configs/path_mapping.yaml").resolve(),
            )
        )
