"""Agent router that dispatches to configured plugins."""

from __future__ import annotations

from app.agents.base import (
    AuthorAgentInput,
    AuthorAgentOutput,
    ReviewerAgentInput,
    ReviewerAgentOutput,
)
from app.agents.registry import AgentRegistry


class AgentRouter:
    def __init__(self, registry: AgentRegistry) -> None:
        self._registry = registry
        self._author = registry.build_author_plugin()
        self._reviewer = registry.build_reviewer_plugin()
        self.max_revision_loops = registry.max_revision_loops()

    def run_author(self, payload: AuthorAgentInput) -> AuthorAgentOutput:
        return self._author.run(payload)

    def run_reviewer(self, payload: ReviewerAgentInput) -> ReviewerAgentOutput:
        return self._reviewer.run(payload)
