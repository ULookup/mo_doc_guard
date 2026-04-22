"""Plugin registry and concrete plugin implementations."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import time
from typing import Any

import yaml

from app.agents.base import (
    AuthorAgentInput,
    AuthorAgentOutput,
    ReviewerAgentInput,
    ReviewerAgentOutput,
)
from app.connectors.mcp_agent_client import MCPAgentClient
from app.connectors.model_router import ModelRouter

logger = logging.getLogger(__name__)


@dataclass
class MCPAuthorPlugin:
    endpoint: str
    model_router: ModelRouter
    system_prompt: str

    def run(self, payload: AuthorAgentInput) -> AuthorAgentOutput:
        attempts = _env_int("MCP_AUTHOR_RETRIES", 3, minimum=1)
        backoff_seconds = _env_float("MCP_AUTHOR_RETRY_BACKOFF_SECONDS", 1.0, minimum=0.0)
        client = MCPAgentClient(
            self.endpoint,
            timeout_seconds=_env_int("MCP_AGENT_TIMEOUT_SECONDS", 45, minimum=1),
        )
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                logger.info("author.mcp.attempt started attempt=%s/%s endpoint=%s", attempt, attempts, self.endpoint)
                response = client.invoke(
                    role="author",
                    payload={
                        "prev_tag": payload.prev_tag,
                        "new_tag": payload.new_tag,
                        "evidence_bundle": payload.evidence_bundle,
                        "release_notes": payload.release_notes,
                        "diff_content": payload.diff_content,
                        "review_feedback": payload.review_feedback,
                    },
                    model_spec=self.model_router.resolve("author"),
                    system_prompt=self.system_prompt,
                )
                claims = _validate_author_claims(response.get("claims"))
                return AuthorAgentOutput(
                    doc_patch_diff=str(response.get("doc_patch_diff", "")),
                    change_summary_md=str(response.get("change_summary_md", "")),
                    claims=claims,
                    evidence_map=response.get("evidence_map", {}),
                )
            except (ValueError, RuntimeError, TimeoutError) as exc:
                last_error = exc
                if attempt == attempts or not _is_retryable_mcp_author_error(str(exc)):
                    logger.error(
                        "author.mcp.attempt failed attempt=%s/%s retryable=%s error=%s",
                        attempt,
                        attempts,
                        _is_retryable_mcp_author_error(str(exc)),
                        str(exc),
                    )
                    raise
                logger.warning(
                    "author.mcp.attempt retrying attempt=%s/%s sleep_seconds=%.1f error=%s",
                    attempt,
                    attempts,
                    backoff_seconds * attempt,
                    str(exc),
                )
                time.sleep(backoff_seconds * attempt)
        if last_error is not None:
            raise last_error
        raise RuntimeError("MCP author invocation failed without a specific error")


@dataclass
class MCPReviewerPlugin:
    endpoint: str
    model_router: ModelRouter
    system_prompt: str

    def run(self, payload: ReviewerAgentInput) -> ReviewerAgentOutput:
        client = MCPAgentClient(
            self.endpoint,
            timeout_seconds=_env_int("MCP_AGENT_TIMEOUT_SECONDS", 45, minimum=1),
        )
        response = client.invoke(
            role="reviewer",
            payload={
                "doc_patch_diff": payload.doc_patch_diff,
                "claims": payload.claims,
                "evidence_bundle": payload.evidence_bundle,
                "pr_url": payload.pr_url,
                "pr_context": payload.pr_context,
            },
            model_spec=self.model_router.resolve("reviewer"),
            system_prompt=self.system_prompt,
        )
        raw_decision = str(response.get("decision", "changes_requested"))
        decision = (
            raw_decision
            if raw_decision in {"approved", "changes_requested", "rejected"}
            else "changes_requested"
        )
        blocking = response.get("blocking_issues", [])
        return ReviewerAgentOutput(
            decision=decision,
            comments=str(response.get("comments", "")),
            blocking_issues=blocking if isinstance(blocking, list) else [],
            review_report=response.get("review_report", {}),
            verification_map=response.get("verification_map", {}),
        )


class AgentRegistry:
    def __init__(
        self,
        agents_config_path: Path,
        prompts_config_path: Path,
        model_router: ModelRouter,
        path_mapping_file: Path,
    ) -> None:
        self.agents_config = self._load_yaml(agents_config_path)
        self.prompts_config = self._load_yaml(prompts_config_path)
        self.model_router = model_router
        self.path_mapping_file = path_mapping_file
        self.agent_only = os.getenv("AGENT_ONLY", "true").strip().lower() in {"1", "true", "yes", "on"}
        if self.agent_only:
            self._validate_agent_only_defaults()

    def build_author_plugin(self) -> Any:
        plugin_id = str(
            self.agents_config.get("defaults", {}).get("author_plugin", "mcp_author")
        )
        plugin_cfg = self._plugin_config(plugin_id)
        plugin_type = str(plugin_cfg.get("type", "mcp_author"))
        if plugin_type == "mcp_author":
            endpoint = str(plugin_cfg.get("endpoint", "")).strip() or os.getenv(
                "MCP_AUTHOR_ENDPOINT", ""
            ).strip()
            if not endpoint:
                raise ValueError("MCP_AUTHOR_ENDPOINT is required when author plugin is mcp_author")
            prompt = str(
                self.prompts_config.get("author", {}).get(
                    "system",
                    "You are an evidence-based documentation author.",
                )
            )
            return MCPAuthorPlugin(endpoint=endpoint, model_router=self.model_router, system_prompt=prompt)
        raise ValueError(f"unsupported author plugin type: {plugin_type}; only mcp_author is allowed")

    def build_reviewer_plugin(self) -> Any:
        plugin_id = str(
            self.agents_config.get("defaults", {}).get("reviewer_plugin", "mcp_reviewer")
        )
        plugin_cfg = self._plugin_config(plugin_id)
        plugin_type = str(plugin_cfg.get("type", "mcp_reviewer"))
        if plugin_type == "mcp_reviewer":
            endpoint = str(plugin_cfg.get("endpoint", "")).strip() or os.getenv(
                "MCP_REVIEWER_ENDPOINT", ""
            ).strip()
            if not endpoint:
                raise ValueError(
                    "MCP_REVIEWER_ENDPOINT is required when reviewer plugin is mcp_reviewer"
                )
            prompt = str(
                self.prompts_config.get("reviewer", {}).get(
                    "system",
                    "You are a strict evidence-based documentation reviewer.",
                )
            )
            return MCPReviewerPlugin(
                endpoint=endpoint,
                model_router=self.model_router,
                system_prompt=prompt,
            )
        raise ValueError(f"unsupported reviewer plugin type: {plugin_type}; only mcp_reviewer is allowed")

    def max_revision_loops(self) -> int:
        return int(self.agents_config.get("defaults", {}).get("max_revision_loops", 2))

    def _plugin_config(self, plugin_id: str) -> dict[str, Any]:
        plugins = self.agents_config.get("plugins", {})
        if not isinstance(plugins, dict):
            raise ValueError("agents.plugins must be a mapping")
        cfg = plugins.get(plugin_id, {})
        if not isinstance(cfg, dict):
            raise ValueError(f"invalid plugin config for {plugin_id}")
        return cfg

    def _validate_agent_only_defaults(self) -> None:
        defaults = self.agents_config.get("defaults", {})
        if not isinstance(defaults, dict):
            raise ValueError("agents.defaults must be a mapping")
        author_plugin = str(defaults.get("author_plugin", "")).strip()
        reviewer_plugin = str(defaults.get("reviewer_plugin", "")).strip()
        if author_plugin and not author_plugin.startswith("mcp_"):
            raise ValueError("AGENT_ONLY mode requires defaults.author_plugin to be an mcp plugin")
        if reviewer_plugin and not reviewer_plugin.startswith("mcp_"):
            raise ValueError("AGENT_ONLY mode requires defaults.reviewer_plugin to be an mcp plugin")

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        if not isinstance(data, dict):
            raise ValueError(f"invalid yaml config: {path}")
        return data


def _validate_author_claims(raw_claims: Any) -> dict[str, Any]:
    if not isinstance(raw_claims, dict):
        raise ValueError("invalid MCP author response: claims must be an object")
    claims_list = raw_claims.get("claims")
    if not isinstance(claims_list, list):
        raise ValueError("invalid MCP author response: claims.claims must be a list")
    claim_count = raw_claims.get("claim_count")
    if not isinstance(claim_count, int):
        raise ValueError("invalid MCP author response: claims.claim_count must be an integer")
    if claim_count != len(claims_list):
        raise ValueError("invalid MCP author response: claims.claim_count does not match claims length")
    return raw_claims


def _is_retryable_mcp_author_error(message: str) -> bool:
    lowered = message.lower()
    markers = [
        "claims must be an object",
        "claims.claims must be a list",
        "claims.claim_count must be an integer",
        "claims.claim_count does not match claims length",
        "timed out",
        "couldn't connect",
        "failed to connect",
        "connection reset",
        "bad gateway",
        "502",
    ]
    return any(marker in lowered for marker in markers)


def _env_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, *, minimum: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, value)


# Backward-compatible aliases to avoid breaking existing references.
McpAuthorPlugin = MCPAuthorPlugin
McpReviewerPlugin = MCPReviewerPlugin
