"""HTTP-based MCP-style external agent client."""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

from app.connectors.model_router import ModelSpec

logger = logging.getLogger(__name__)


class MCPAgentClient:
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
        started_at = time.perf_counter()
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
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:  # noqa: S310
                decoded = response.read().decode("utf-8")
        except HTTPError as exc:
            logger.error(
                "mcp.invoke.http_error role=%s endpoint=%s status=%s timeout_seconds=%s elapsed_ms=%s",
                role,
                self.endpoint,
                exc.code,
                self.timeout_seconds,
                int((time.perf_counter() - started_at) * 1000),
            )
            raise
        except URLError as exc:
            logger.error(
                "mcp.invoke.url_error role=%s endpoint=%s timeout_seconds=%s elapsed_ms=%s reason=%s",
                role,
                self.endpoint,
                self.timeout_seconds,
                int((time.perf_counter() - started_at) * 1000),
                str(exc.reason),
            )
            raise
        result = json.loads(decoded)
        if not isinstance(result, dict):
            raise ValueError("invalid MCP agent response")
        logger.info(
            "mcp.invoke.success role=%s endpoint=%s model=%s timeout_seconds=%s elapsed_ms=%s response_keys=%s",
            role,
            self.endpoint,
            model_spec.model,
            self.timeout_seconds,
            int((time.perf_counter() - started_at) * 1000),
            ",".join(sorted(result.keys())),
        )
        return result


# Backward-compatible alias for existing imports.
McpAgentClient = MCPAgentClient
