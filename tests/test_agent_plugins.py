from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.base import AuthorAgentInput
from app.agents.registry import AgentRegistry, MCPAuthorPlugin
from app.agents.router import AgentRouter
from app.connectors.model_router import ModelRouter


def test_agent_router_requires_mcp_endpoints_when_agent_only(monkeypatch) -> None:
    monkeypatch.delenv("MCP_AUTHOR_ENDPOINT", raising=False)
    monkeypatch.delenv("MCP_REVIEWER_ENDPOINT", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("AGENT_ONLY", "true")
    repo_root = Path(__file__).resolve().parents[1]
    registry = AgentRegistry(
        agents_config_path=repo_root / "configs" / "agents.yaml",
        prompts_config_path=repo_root / "configs" / "prompts.yaml",
        model_router=ModelRouter(repo_root / "configs" / "models.yaml"),
        path_mapping_file=repo_root / "configs" / "path_mapping.yaml",
    )
    with pytest.raises(ValueError, match="MCP_AUTHOR_ENDPOINT"):
        AgentRouter(registry)


def test_registry_non_dev_requires_mcp_endpoint(tmp_path: Path, monkeypatch) -> None:
    agents_config = tmp_path / "agents.yaml"
    models_config = tmp_path / "models.yaml"
    prompts_config = tmp_path / "prompts.yaml"
    path_mapping_file = Path(__file__).resolve().parents[1] / "configs" / "path_mapping.yaml"
    agents_config.write_text(
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
    models_config.write_text(
        "\n".join(
            [
                "default:",
                "  provider: anthropic",
                "  model: MiniMax-M2.5",
            ]
        ),
        encoding="utf-8",
    )
    prompts_config.write_text("author:\n  system: test\n", encoding="utf-8")
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("AGENT_ONLY", "true")
    monkeypatch.delenv("MCP_AUTHOR_ENDPOINT", raising=False)
    monkeypatch.delenv("MCP_REVIEWER_ENDPOINT", raising=False)

    with pytest.raises(ValueError, match="MCP_AUTHOR_ENDPOINT"):
        AgentRegistry(
            agents_config_path=agents_config,
            prompts_config_path=prompts_config,
            model_router=ModelRouter(models_config),
            path_mapping_file=path_mapping_file,
        ).build_author_plugin()


def test_mcp_author_plugin_rejects_invalid_claims_shape(monkeypatch, tmp_path: Path) -> None:
    model_config = tmp_path / "models.yaml"
    model_config.write_text(
        "\n".join(
            [
                "default:",
                "  provider: anthropic",
                "  model: MiniMax-M2.5",
            ]
        ),
        encoding="utf-8",
    )
    plugin = MCPAuthorPlugin(
        endpoint="http://127.0.0.1:8787/invoke",
        model_router=ModelRouter(model_config),
        system_prompt="author prompt",
    )
    monkeypatch.setattr(
        "app.connectors.mcp_agent_client.MCPAgentClient.invoke",
        lambda self, **kwargs: {
            "doc_patch_diff": "",
            "change_summary_md": "summary",
            "claims": ["invalid-shape"],
            "evidence_map": {},
        },
    )
    with pytest.raises(ValueError, match="claims must be an object"):
        plugin.run(
            AuthorAgentInput(
                prev_tag="v1.0.0",
                new_tag="v1.1.0",
                evidence_bundle={"retrieval_scope": []},
                release_notes="",
                diff_content="",
            )
        )


def test_mcp_author_plugin_retries_invalid_claims_then_succeeds(monkeypatch, tmp_path: Path) -> None:
    model_config = tmp_path / "models.yaml"
    model_config.write_text(
        "\n".join(
            [
                "default:",
                "  provider: anthropic",
                "  model: MiniMax-M2.5",
            ]
        ),
        encoding="utf-8",
    )
    plugin = MCPAuthorPlugin(
        endpoint="http://127.0.0.1:8787/invoke",
        model_router=ModelRouter(model_config),
        system_prompt="author prompt",
    )
    monkeypatch.setenv("MCP_AUTHOR_RETRIES", "3")
    monkeypatch.setenv("MCP_AUTHOR_RETRY_BACKOFF_SECONDS", "0")
    call_count = {"n": 0}

    def fake_invoke(self, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "doc_patch_diff": "",
                "change_summary_md": "summary",
                "claims": ["invalid-shape"],
                "evidence_map": {},
            }
        return {
            "doc_patch_diff": "diff --git a/docs/a.md b/docs/a.md",
            "change_summary_md": "summary",
            "claims": {"claim_count": 0, "claims": []},
            "evidence_map": {},
        }

    monkeypatch.setattr("app.connectors.mcp_agent_client.MCPAgentClient.invoke", fake_invoke)
    output = plugin.run(
        AuthorAgentInput(
            prev_tag="v1.0.0",
            new_tag="v1.1.0",
            evidence_bundle={"retrieval_scope": []},
            release_notes="",
            diff_content="",
        )
    )
    assert call_count["n"] == 2
    assert output.claims == {"claim_count": 0, "claims": []}
