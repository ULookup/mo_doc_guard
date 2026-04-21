from __future__ import annotations

from pathlib import Path

from app.connectors.model_router import ModelRouter


def test_model_router_resolves_role_override(tmp_path: Path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        "\n".join(
            [
                "default:",
                "  provider: openai",
                "  model: gpt-default",
                "  temperature: 0.1",
                "  max_tokens: 1000",
                "roles:",
                "  reviewer:",
                "    provider: anthropic",
                "    model: claude-test",
                "    temperature: 0.0",
                "    max_tokens: 2000",
                "    fallback_provider: openai",
                "    fallback_model: gpt-fallback",
            ]
        ),
        encoding="utf-8",
    )
    router = ModelRouter(config_path)
    spec = router.resolve("reviewer")
    assert spec.provider == "anthropic"
    assert spec.model == "claude-test"
    assert spec.fallback_provider == "openai"
    assert spec.fallback_model == "gpt-fallback"


def test_model_router_uses_default_for_unknown_role(tmp_path: Path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        "\n".join(
            [
                "default:",
                "  provider: openai",
                "  model: gpt-default",
                "  temperature: 0.2",
                "  max_tokens: 3000",
            ]
        ),
        encoding="utf-8",
    )
    router = ModelRouter(config_path)
    spec = router.resolve("author")
    assert spec.provider == "openai"
    assert spec.model == "gpt-default"
    assert spec.temperature == 0.2
    assert spec.max_tokens == 3000
