from __future__ import annotations

from app.connectors.matrixone_evidence import resolve_prev_tag
from app.core.settings import load_settings
from app.retrieval.incremental_scope import build_retrieval_scope


def test_settings_empty_paths_fallback_to_defaults(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("MATRIXONE_REPO_DIR", "")
    monkeypatch.setenv("DOCS_REPO_DIR", "")
    settings = load_settings()
    assert str(settings.matrixone_repo_dir).endswith("/repos/matrixone")
    assert str(settings.docs_repo_dir).endswith("/repos/matrixorigin.io")


def test_resolve_prev_tag_dry_run_without_input_uses_placeholder(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    settings = load_settings()
    prev = resolve_prev_tag(
        settings=settings,
        new_tag="v2.0.0",
        prev_tag=None,
        dry_run=True,
    )
    assert prev == "__dry_run_prev_tag__"


def test_incremental_scope_requires_path_boundary() -> None:
    scope = build_retrieval_scope(
        changed_files=["pkg/sql/parsers2/extra.go", "pkg/sql/parsers/parser.go"],
        path_mappings=[
            {
                "code_path_prefix": "pkg/sql/parsers",
                "docs_path": "docs/sql-reference/sql-syntax.md",
                "topic": "sql_syntax",
            }
        ],
    )
    assert scope[0]["in_scope"] is False
    assert scope[1]["in_scope"] is True
