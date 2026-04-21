"""HTTP-based MCP-style external agent client."""

from __future__ import annotations

import json
from typing import Any
from urllib import request

from app.connectors.model_router import ModelSpec


class McpAgentClient:
    def __init__(self, endpoint: str, timeout_seconds: int = 60) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds

    def invoke(
        self,
        *,
        role: str,
        payload: dict[str, Any],
        model_spec: ModelSpec,
        system_prompt: str,
    ) -> dict[str, Any]:
        body = {
            "role": role,
            "payload": payload,
            "model": {
                "provider": model_spec.provider,
                "name": model_spec.model,
                "temperature": model_spec.temperature,
                "max_tokens": model_spec.max_tokens,
                "fallback_provider": model_spec.fallback_provider,
                "fallback_model": model_spec.fallback_model,
            },
            "system_prompt": system_prompt,
        }
        encoded = json.dumps(body).encode("utf-8")
        http_request = request.Request(
            self.endpoint,
            data=encoded,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(http_request, timeout=self.timeout_seconds) as response:  # noqa: S310
            decoded = response.read().decode("utf-8")
        result = json.loads(decoded)
        if not isinstance(result, dict):
            raise ValueError("invalid MCP agent response")
        return result
