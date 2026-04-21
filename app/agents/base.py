"""Plugin contracts for author and reviewer agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol


@dataclass
class AuthorAgentInput:
    prev_tag: str
    new_tag: str
    evidence_bundle: dict[str, Any]
    release_notes: str
    diff_content: str
    review_feedback: str | None = None


@dataclass
class AuthorAgentOutput:
    doc_patch_diff: str
    change_summary_md: str
    claims: dict[str, Any]
    evidence_map: dict[str, Any]


@dataclass
class ReviewerAgentInput:
    doc_patch_diff: str
    claims: dict[str, Any]
    evidence_bundle: dict[str, Any]
    pr_url: str
    pr_context: dict[str, Any]


@dataclass
class ReviewerAgentOutput:
    decision: Literal["approved", "changes_requested", "rejected"]
    comments: str
    blocking_issues: list[str]
    review_report: dict[str, Any]
    verification_map: dict[str, Any]


class AuthorAgentPlugin(Protocol):
    def run(self, payload: AuthorAgentInput) -> AuthorAgentOutput:
        ...


class ReviewerAgentPlugin(Protocol):
    def run(self, payload: ReviewerAgentInput) -> ReviewerAgentOutput:
        ...
