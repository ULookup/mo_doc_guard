"""Incremental retrieval scope based on tag diff changed files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_path_mappings(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    mappings = data.get("mappings", [])
    return [item for item in mappings if isinstance(item, dict)]


def build_retrieval_scope(
    changed_files: list[str],
    path_mappings: list[dict[str, str]],
) -> list[dict[str, Any]]:
    scope: list[dict[str, Any]] = []
    for file_path in changed_files:
        matches: list[dict[str, str]] = []
        for mapping in path_mappings:
            prefix = str(mapping.get("code_path_prefix", ""))
            if prefix and (file_path == prefix or file_path.startswith(f"{prefix}/")):
                matches.append(
                    {
                        "topic": str(mapping.get("topic", "")),
                        "docs_path": str(mapping.get("docs_path", "")),
                    }
                )
        scope.append(
            {
                "code_path": file_path,
                "mapped_docs": matches,
                "in_scope": len(matches) > 0,
            }
        )
    return scope
