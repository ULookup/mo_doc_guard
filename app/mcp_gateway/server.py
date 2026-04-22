"""Local MCP gateway service for author/reviewer plugins."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yaml


LOGGER = logging.getLogger("mcp_gateway")


class ModelPayload(BaseModel):
    provider: str = "anthropic"
    name: str
    temperature: float = 0.0
    max_tokens: int = 2048
    fallback_provider: str | None = None
    fallback_model: str | None = None


class InvokeRequest(BaseModel):
    role: Literal["author", "reviewer"]
    payload: dict[str, Any]
    model: ModelPayload
    system_prompt: str


class HealthResponse(BaseModel):
    status: str
    anthropic_base_url: str
    mock_mode: bool


app = FastAPI(title="docs-agent-ops MCP Gateway", version="1.0.0")


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(
        status="ok",
        anthropic_base_url=_anthropic_base_url(),
        mock_mode=_mock_mode(),
    )


@app.post("/invoke")
def invoke(req: InvokeRequest) -> dict[str, Any]:
    if req.role == "author":
        return _invoke_author(req)
    if req.role == "reviewer":
        return _invoke_reviewer(req)
    raise HTTPException(status_code=400, detail=f"unsupported role: {req.role}")


def _invoke_author(req: InvokeRequest) -> dict[str, Any]:
    if _mock_mode():
        return {
            "doc_patch_diff": "",
            "change_summary_md": "No changes generated in mock mode.",
            "claims": {"claim_count": 0, "claims": []},
            "evidence_map": {"mode": "mock"},
        }

    raw_result: Any = None
    try:
        prompt = _build_author_prompt(req)
        result = _call_anthropic_json(req.model, prompt)
        raw_result = result
        claims = _validate_author_claims(result.get("claims"))
        allowed_docs_paths = _load_allowed_docs_paths()
        _validate_claims_provenance_and_paths(claims, allowed_docs_paths)
        doc_patch_diff = result.get("doc_patch_diff", "")
        if not isinstance(doc_patch_diff, str):
            raise HTTPException(status_code=502, detail="invalid author response: doc_patch_diff must be a string")
        _validate_patch_paths(doc_patch_diff, allowed_docs_paths)
        if _requires_doc_update(req.payload):
            if not doc_patch_diff.strip():
                raise HTTPException(
                    status_code=502,
                    detail="invalid author response: non-empty doc_patch_diff is required for substantive evidence",
                )
            if int(claims.get("claim_count", 0)) <= 0:
                raise HTTPException(
                    status_code=502,
                    detail="invalid author response: claims are required for substantive evidence",
                )
        change_summary_md = result.get("change_summary_md", "")
        if not isinstance(change_summary_md, str):
            raise HTTPException(
                status_code=502,
                detail="invalid author response: change_summary_md must be a string",
            )
        evidence_map = result.get("evidence_map", {})
        if not isinstance(evidence_map, dict):
            raise HTTPException(status_code=502, detail="invalid author response: evidence_map must be an object")
        return {
            "doc_patch_diff": doc_patch_diff,
            "change_summary_md": change_summary_md,
            "claims": claims,
            "evidence_map": evidence_map,
        }
    except HTTPException as exc:
        LOGGER.warning(
            "author invoke rejected detail=%s raw_result_preview=%s",
            exc.detail,
            _preview_json(raw_result),
        )
        raise


def _invoke_reviewer(req: InvokeRequest) -> dict[str, Any]:
    if _mock_mode():
        return {
            "decision": "changes_requested",
            "comments": "mock mode reviewer: no real model call",
            "blocking_issues": ["mcp_gateway mock mode is enabled"],
            "review_report": {"decision": "fail", "claim_results": []},
            "verification_map": {"mode": "mock"},
        }

    prompt = _build_reviewer_prompt(req)
    result = _call_anthropic_json(req.model, prompt)
    decision_raw = str(result.get("decision", "changes_requested"))
    decision = (
        decision_raw
        if decision_raw in {"approved", "changes_requested", "rejected"}
        else "changes_requested"
    )
    blocking_issues = result.get("blocking_issues", [])
    if not isinstance(blocking_issues, list):
        blocking_issues = []
    return {
        "decision": decision,
        "comments": str(result.get("comments", "")),
        "blocking_issues": blocking_issues,
        "review_report": result.get("review_report", {}),
        "verification_map": result.get("verification_map", {}),
    }


def _call_anthropic_json(model: ModelPayload, user_prompt: str) -> dict[str, Any]:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY is required")

    payload = {
        "model": model.name,
        "max_tokens": int(model.max_tokens),
        "temperature": float(model.temperature),
        "messages": [{"role": "user", "content": user_prompt}],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        # Keep x-api-key for compatibility with providers/gateways that still read it.
        "x-api-key": api_key,
        "anthropic-version": os.getenv("ANTHROPIC_VERSION", "2023-06-01"),
        "content-type": "application/json",
    }

    response_json = _post_with_retry(
        url=f"{_anthropic_base_url().rstrip('/')}/v1/messages",
        headers=headers,
        payload=payload,
    )
    text = _extract_text_from_anthropic_response(response_json)
    parsed = _extract_json_object(text)
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="model response is not a JSON object")
    return parsed


def _post_with_retry(*, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    timeout_seconds = float(os.getenv("MCP_GATEWAY_TIMEOUT_SECONDS", "60"))
    retries = int(os.getenv("MCP_GATEWAY_RETRIES", "2"))
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("invalid non-object response")
                return data
        except httpx.HTTPStatusError as exc:
            response_text = ""
            try:
                response_text = exc.response.text
            except Exception:  # noqa: BLE001
                response_text = ""
            last_error = exc
            LOGGER.warning(
                "anthropic call failed attempt=%s status=%s body=%s",
                attempt + 1,
                exc.response.status_code,
                response_text[:600],
            )
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            LOGGER.warning("anthropic call failed attempt=%s error=%s", attempt + 1, exc)
    raise HTTPException(status_code=502, detail=f"anthropic upstream failed: {last_error}")


def _extract_text_from_anthropic_response(data: dict[str, Any]) -> str:
    content = data.get("content", [])
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
        return "\n".join(text_parts).strip()
    return ""


def _extract_json_object(text: str) -> Any:
    raw = text.strip()
    if not raw:
        raise HTTPException(status_code=502, detail="empty model response")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise HTTPException(status_code=502, detail="response does not include JSON")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=502, detail=f"invalid JSON payload: {exc}") from exc


def _build_author_prompt(req: InvokeRequest) -> str:
    allowed_docs_paths = sorted(_load_allowed_docs_paths())
    return (
        f"{req.system_prompt}\n\n"
        "You MUST return ONLY a valid JSON object with EXACT keys:\n"
        "  - doc_patch_diff (string)\n"
        "  - change_summary_md (string)\n"
        "  - claims (object)\n"
        "  - evidence_map (object)\n\n"
        "STRICT CLAIMS CONTRACT:\n"
        "  - claims MUST be: {\"claim_count\": <int>, \"claims\": <array>}\n"
        "  - claims.claim_count MUST exactly equal len(claims.claims)\n"
        "  - each claim MUST include: claim_id, docs_path, evidence\n"
        "  - evidence MUST include: code_path, reason\n"
        "  - docs_path MUST be in ALLOWED_DOCS_PATHS\n\n"
        "STRICT PATCH CONTRACT:\n"
        "  - doc_patch_diff MUST be a valid unified git diff string\n"
        "  - each file MUST start with: diff --git a/<path> b/<path>\n"
        "  - <path> MUST be in ALLOWED_DOCS_PATHS\n"
        "  - plain text, tag names, or markdown are NOT allowed in doc_patch_diff\n"
        "  - do NOT output '---/+++' only patches without a diff --git header\n\n"
        "SUBSTANTIVE RULE:\n"
        "  - if payload.evidence_bundle.retrieval_scope is non-empty, doc_patch_diff MUST be non-empty\n"
        "  - in that case, claims.claim_count MUST be > 0\n\n"
        "VALID doc_patch_diff EXAMPLE:\n"
        "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/sql-syntax.md\n"
        "@@ -10,0 +11,2 @@\n"
        "+Added sentence from evidence.\n"
        "+Another line.\n\n"
        "Use evidence from payload only. No markdown fences.\n\n"
        f"ALLOWED_DOCS_PATHS: {json.dumps(allowed_docs_paths, ensure_ascii=False)}\n"
        f"ROLE: {req.role}\n"
        f"PAYLOAD:\n{json.dumps(req.payload, ensure_ascii=False)}"
    )


def _build_reviewer_prompt(req: InvokeRequest) -> str:
    return (
        f"{req.system_prompt}\n\n"
        "Return ONLY JSON object with keys: "
        "decision, comments, blocking_issues, review_report, verification_map.\n"
        "decision must be one of approved/changes_requested/rejected.\n"
        "No markdown fences.\n\n"
        f"ROLE: {req.role}\n"
        f"PAYLOAD:\n{json.dumps(req.payload, ensure_ascii=False)}"
    )


def _anthropic_base_url() -> str:
    return os.getenv("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic").strip()


def _mock_mode() -> bool:
    return os.getenv("MCP_GATEWAY_MOCK", "false").strip().lower() in {"1", "true", "yes", "on"}


def _validate_author_claims(raw_claims: Any) -> dict[str, Any]:
    if not isinstance(raw_claims, dict):
        raise HTTPException(status_code=502, detail="invalid author response: claims must be an object")
    claims = raw_claims.get("claims")
    if not isinstance(claims, list):
        raise HTTPException(status_code=502, detail="invalid author response: claims.claims must be a list")
    claim_count = raw_claims.get("claim_count")
    if not isinstance(claim_count, int):
        raise HTTPException(
            status_code=502,
            detail="invalid author response: claims.claim_count must be an integer",
        )
    if claim_count != len(claims):
        raise HTTPException(
            status_code=502,
            detail="invalid author response: claims.claim_count does not match claims length",
        )
    return raw_claims


def _validate_claims_provenance_and_paths(claims_obj: dict[str, Any], allowed_docs_paths: set[str]) -> None:
    claims = claims_obj.get("claims", [])
    for claim in claims:
        if not isinstance(claim, dict):
            raise HTTPException(status_code=502, detail="invalid author response: each claim must be an object")
        docs_path = str(claim.get("docs_path", "")).strip()
        if not docs_path:
            raise HTTPException(status_code=502, detail="invalid author response: claim.docs_path is required")
        if docs_path not in allowed_docs_paths:
            raise HTTPException(status_code=502, detail="invalid author response: claim.docs_path outside whitelist")
        evidence = claim.get("evidence", {})
        if not isinstance(evidence, dict):
            raise HTTPException(status_code=502, detail="invalid author response: claim.evidence must be an object")
        code_path = str(evidence.get("code_path", "")).strip()
        reason = str(evidence.get("reason", "")).strip()
        if not code_path or not reason:
            raise HTTPException(
                status_code=502,
                detail="invalid author response: claim.evidence.code_path and claim.evidence.reason are required",
            )


def _validate_patch_paths(doc_patch_diff: str, allowed_docs_paths: set[str]) -> None:
    if not doc_patch_diff.strip():
        return
    matched = False
    for line in doc_patch_diff.splitlines():
        if not line.startswith("diff --git "):
            continue
        matched = True
        parts = line.split()
        if len(parts) < 4 or not parts[2].startswith("a/") or not parts[3].startswith("b/"):
            raise HTTPException(status_code=502, detail="invalid author response: malformed diff header")
        a_path = parts[2][2:]
        b_path = parts[3][2:]
        if a_path != b_path:
            raise HTTPException(status_code=502, detail="invalid author response: patch path mismatch")
        if a_path not in allowed_docs_paths:
            raise HTTPException(status_code=502, detail="invalid author response: patch path outside whitelist")
    if not matched:
        raise HTTPException(status_code=502, detail="invalid author response: patch must use git diff format")


def _load_allowed_docs_paths() -> set[str]:
    path_mapping_file = Path(os.getenv("PATH_MAPPING_FILE", "configs/path_mapping.yaml"))
    if not path_mapping_file.is_absolute():
        path_mapping_file = Path.cwd() / path_mapping_file
    if not path_mapping_file.exists():
        return set()
    with path_mapping_file.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    mappings = data.get("mappings", []) if isinstance(data, dict) else []
    allowed = {
        str(item.get("docs_path", "")).strip()
        for item in mappings
        if isinstance(item, dict) and str(item.get("docs_path", "")).strip()
    }
    if not allowed:
        raise HTTPException(status_code=500, detail="path mapping does not include docs paths")
    return allowed


def _requires_doc_update(payload: dict[str, Any]) -> bool:
    evidence = payload.get("evidence_bundle", {})
    if not isinstance(evidence, dict):
        return False
    retrieval_scope = evidence.get("retrieval_scope", [])
    if isinstance(retrieval_scope, list):
        for item in retrieval_scope:
            if isinstance(item, dict) and bool(item.get("in_scope", False)):
                return True
    return False


def _preview_json(value: Any, max_chars: int = 600) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        rendered = repr(value)
    return rendered[:max_chars]
