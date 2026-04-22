from __future__ import annotations

import pytest

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


def test_load_settings_reads_local_dotenv(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "APP_ENV=dev",
                "MATRIXORIGIN_DOCS_REPO=https://github.com/example/docs.git",
                "DOCS_REPO_TOKEN=test-token",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("MATRIXORIGIN_DOCS_REPO", raising=False)
    monkeypatch.delenv("DOCS_REPO_TOKEN", raising=False)
    settings = load_settings()
    assert settings.matrixorigin_docs_repo == "https://github.com/example/docs.git"
    assert settings.docs_repo_token == "test-token"


def test_load_settings_non_dev_requires_mcp_endpoints(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents.yaml").write_text(
        "\n".join(
            [
                "defaults:",
                "  author_plugin: mcp_author",
                "  reviewer_plugin: mcp_reviewer",
                "plugins:",
                "  mcp_author:",
                "    type: mcp_author",
                "    endpoint: \"\"",
                "  mcp_reviewer:",
                "    type: mcp_reviewer",
                "    endpoint: \"\"",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "models.yaml").write_text(
        "\n".join(
            [
                "default:",
                "  provider: anthropic",
                "  model: MiniMax-M2.5",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("MATRIXONE_REPO", "git@github.com:matrixorigin/matrixone.git")
    monkeypatch.setenv("MATRIXORIGIN_DOCS_REPO", "https://github.com/matrixorigin/matrixorigin.io.git")
    monkeypatch.setenv("AGENTS_CONFIG_PATH", str(tmp_path / "agents.yaml"))
    monkeypatch.setenv("MODELS_CONFIG_PATH", str(tmp_path / "models.yaml"))
    monkeypatch.delenv("MCP_AUTHOR_ENDPOINT", raising=False)
    monkeypatch.delenv("MCP_REVIEWER_ENDPOINT", raising=False)
    with pytest.raises(ValueError, match="MCP_AUTHOR_ENDPOINT"):
        load_settings()


def test_load_settings_non_dev_accepts_env_endpoints(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "agents.yaml").write_text(
        "\n".join(
            [
                "defaults:",
                "  author_plugin: mcp_author",
                "  reviewer_plugin: mcp_reviewer",
                "plugins:",
                "  mcp_author:",
                "    type: mcp_author",
                "    endpoint: \"\"",
                "  mcp_reviewer:",
                "    type: mcp_reviewer",
                "    endpoint: \"\"",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "models.yaml").write_text(
        "\n".join(
            [
                "default:",
                "  provider: anthropic",
                "  model: MiniMax-M2.5",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("MATRIXONE_REPO", "git@github.com:matrixorigin/matrixone.git")
    monkeypatch.setenv("MATRIXORIGIN_DOCS_REPO", "https://github.com/matrixorigin/matrixorigin.io.git")
    monkeypatch.setenv("AGENTS_CONFIG_PATH", str(tmp_path / "agents.yaml"))
    monkeypatch.setenv("MODELS_CONFIG_PATH", str(tmp_path / "models.yaml"))
    monkeypatch.setenv("MCP_AUTHOR_ENDPOINT", "http://127.0.0.1:8787/invoke")
    monkeypatch.setenv("MCP_REVIEWER_ENDPOINT", "http://127.0.0.1:8787/invoke")
    settings = load_settings()
    assert settings.app_env == "prod"
