"""Plugin registry and concrete plugin implementations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.agents.base import (
    AuthorAgentInput,
    AuthorAgentOutput,
    ReviewerAgentInput,
    ReviewerAgentOutput,
)
from app.connectors.mcp_agent_client import McpAgentClient
from app.connectors.model_router import ModelRouter
from app.skills.mo_doc_reviewer import ReviewerInput, run_reviewer_skill
from app.skills.mo_doc_writer import WriterInput, run_writer_skill


@dataclass
class DeterministicAuthorPlugin:
    path_mapping_file: Path

    def run(self, payload: AuthorAgentInput) -> AuthorAgentOutput:
        output = run_writer_skill(
            WriterInput(
                prev_tag=payload.prev_tag,
                new_tag=payload.new_tag,
                evidence_bundle=payload.evidence_bundle,
                path_mapping_file=self.path_mapping_file,
            )
        )
        return AuthorAgentOutput(
            doc_patch_diff=output.doc_patch_diff,
            change_summary_md=output.change_summary_md,
            claims=output.claims,
            evidence_map={"source": "deterministic_writer"},
        )


@dataclass
class DeterministicReviewerPlugin:
    def run(self, payload: ReviewerAgentInput) -> ReviewerAgentOutput:
        output = run_reviewer_skill(
            ReviewerInput(
                doc_patch_diff=payload.doc_patch_diff,
                claims=payload.claims,
                evidence_bundle=payload.evidence_bundle,
            )
        )
        decision = "approved" if output.decision == "pass" else "changes_requested"
        return ReviewerAgentOutput(
            decision=decision,
            comments="\n".join(output.blocking_issues) if output.blocking_issues else "approved",
            blocking_issues=output.blocking_issues,
            review_report=output.review_report,
            verification_map={"source": "deterministic_reviewer"},
        )


@dataclass
class McpAuthorPlugin:
    endpoint: str
    model_router: ModelRouter
    system_prompt: str

    def run(self, payload: AuthorAgentInput) -> AuthorAgentOutput:
        client = McpAgentClient(self.endpoint)
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
        return AuthorAgentOutput(
            doc_patch_diff=str(response.get("doc_patch_diff", "")),
            change_summary_md=str(response.get("change_summary_md", "")),
            claims=response.get("claims", {}),
            evidence_map=response.get("evidence_map", {}),
        )


@dataclass
class McpReviewerPlugin:
    endpoint: str
    model_router: ModelRouter
    system_prompt: str

    def run(self, payload: ReviewerAgentInput) -> ReviewerAgentOutput:
        client = McpAgentClient(self.endpoint)
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

    def build_author_plugin(self) -> Any:
        plugin_id = str(
            self.agents_config.get("defaults", {}).get("author_plugin", "deterministic_author")
        )
        plugin_cfg = self._plugin_config(plugin_id)
        plugin_type = str(plugin_cfg.get("type", "deterministic_author"))
        if plugin_type == "deterministic_author":
            return DeterministicAuthorPlugin(path_mapping_file=self.path_mapping_file)
        if plugin_type == "mcp_author":
            endpoint = str(plugin_cfg.get("endpoint", "")).strip()
            if not endpoint:
                raise ValueError("mcp_author plugin requires endpoint")
            prompt = str(
                self.prompts_config.get("author", {}).get(
                    "system",
                    "You are an evidence-based documentation author.",
                )
            )
            return McpAuthorPlugin(endpoint=endpoint, model_router=self.model_router, system_prompt=prompt)
        raise ValueError(f"unsupported author plugin type: {plugin_type}")

    def build_reviewer_plugin(self) -> Any:
        plugin_id = str(
            self.agents_config.get("defaults", {}).get("reviewer_plugin", "deterministic_reviewer")
        )
        plugin_cfg = self._plugin_config(plugin_id)
        plugin_type = str(plugin_cfg.get("type", "deterministic_reviewer"))
        if plugin_type == "deterministic_reviewer":
            return DeterministicReviewerPlugin()
        if plugin_type == "mcp_reviewer":
            endpoint = str(plugin_cfg.get("endpoint", "")).strip()
            if not endpoint:
                raise ValueError("mcp_reviewer plugin requires endpoint")
            prompt = str(
                self.prompts_config.get("reviewer", {}).get(
                    "system",
                    "You are a strict evidence-based documentation reviewer.",
                )
            )
            return McpReviewerPlugin(
                endpoint=endpoint,
                model_router=self.model_router,
                system_prompt=prompt,
            )
        raise ValueError(f"unsupported reviewer plugin type: {plugin_type}")

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

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        with path.open("r", encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        if not isinstance(data, dict):
            raise ValueError(f"invalid yaml config: {path}")
        return data
