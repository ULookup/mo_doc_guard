"""Model/provider routing from configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    temperature: float
    max_tokens: int
    fallback_provider: str | None = None
    fallback_model: str | None = None


class ModelRouter:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self._config = self._load_config(config_path)

    def resolve(self, role: str) -> ModelSpec:
        role_cfg = self._config.get("roles", {}).get(role, {})
        default_cfg = self._config.get("default", {})
        merged: dict[str, Any] = {**default_cfg, **role_cfg}
        return ModelSpec(
            provider=str(merged.get("provider", "openai")),
            model=str(merged.get("model", "gpt-4.1-mini")),
            temperature=float(merged.get("temperature", 0.0)),
            max_tokens=int(merged.get("max_tokens", 4096)),
            fallback_provider=(
                str(merged.get("fallback_provider"))
                if merged.get("fallback_provider") is not None
                else None
            ),
            fallback_model=(
                str(merged.get("fallback_model")) if merged.get("fallback_model") is not None else None
            ),
        )

    @staticmethod
    def _load_config(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        if not isinstance(data, dict):
            raise ValueError(f"invalid model config: {path}")
        return data
