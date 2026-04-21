from __future__ import annotations

from pathlib import Path

from app.agents.base import AuthorAgentInput, ReviewerAgentInput
from app.agents.registry import AgentRegistry
from app.agents.router import AgentRouter
from app.connectors.model_router import ModelRouter


def test_agent_router_uses_deterministic_plugins() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    registry = AgentRegistry(
        agents_config_path=repo_root / "configs" / "agents.yaml",
        prompts_config_path=repo_root / "configs" / "prompts.yaml",
        model_router=ModelRouter(repo_root / "configs" / "models.yaml"),
        path_mapping_file=repo_root / "configs" / "path_mapping.yaml",
    )
    router = AgentRouter(registry)

    author_out = router.run_author(
        AuthorAgentInput(
            prev_tag="v0.1.0",
            new_tag="v0.2.0",
            evidence_bundle={
                "retrieval_scope": [],
                "changed_files": [],
                "commits": [],
                "release_notes": "",
                "diff_content": "",
            },
            release_notes="",
            diff_content="",
        )
    )
    assert isinstance(author_out.doc_patch_diff, str)
    assert "claims" in author_out.claims

    reviewer_out = router.run_reviewer(
        ReviewerAgentInput(
            doc_patch_diff=author_out.doc_patch_diff,
            claims=author_out.claims,
            evidence_bundle={
                "retrieval_scope": [],
                "changed_files": [],
                "commits": [],
            },
            pr_url="dry-run://example/pull/1",
            pr_context={},
        )
    )
    assert reviewer_out.decision in {"approved", "changes_requested", "rejected"}
    assert isinstance(reviewer_out.blocking_issues, list)
