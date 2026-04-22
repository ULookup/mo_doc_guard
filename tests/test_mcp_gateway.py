from fastapi.testclient import TestClient

from app.mcp_gateway.server import app


def test_healthz(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic")
    monkeypatch.setenv("MCP_GATEWAY_MOCK", "true")
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["mock_mode"] is True


def test_invoke_author_mock(monkeypatch):
    monkeypatch.setenv("MCP_GATEWAY_MOCK", "true")
    client = TestClient(app)
    response = client.post(
        "/invoke",
        json={
            "role": "author",
            "payload": {"diff": "x"},
            "model": {"provider": "anthropic", "name": "MiniMax-M2.5"},
            "system_prompt": "author prompt",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert "doc_patch_diff" in data
    assert "claims" in data


def test_invoke_reviewer_mock(monkeypatch):
    monkeypatch.setenv("MCP_GATEWAY_MOCK", "true")
    client = TestClient(app)
    response = client.post(
        "/invoke",
        json={
            "role": "reviewer",
            "payload": {"doc_patch_diff": ""},
            "model": {"provider": "anthropic", "name": "MiniMax-M2.5"},
            "system_prompt": "reviewer prompt",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] in {"approved", "changes_requested", "rejected"}
    assert isinstance(data["blocking_issues"], list)


def test_invoke_author_rejects_invalid_claims_shape(monkeypatch):
    monkeypatch.setenv("MCP_GATEWAY_MOCK", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.mcp_gateway.server._call_anthropic_json",
        lambda model, prompt: {
            "doc_patch_diff": "",
            "change_summary_md": "summary",
            "claims": ["invalid"],
            "evidence_map": {},
        },
    )
    client = TestClient(app)
    response = client.post(
        "/invoke",
        json={
            "role": "author",
            "payload": {"diff": "x"},
            "model": {"provider": "anthropic", "name": "MiniMax-M2.5"},
            "system_prompt": "author prompt",
        },
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "invalid author response: claims must be an object"


def test_invoke_author_rejects_claim_docs_path_outside_whitelist(monkeypatch):
    monkeypatch.setenv("MCP_GATEWAY_MOCK", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.mcp_gateway.server._call_anthropic_json",
        lambda model, prompt: {
            "doc_patch_diff": (
                "diff --git a/docs/sql-reference/sql-syntax.md b/docs/sql-reference/sql-syntax.md\n"
                "@@ -1 +1 @@\n"
                "+x\n"
            ),
            "change_summary_md": "summary",
            "claims": {
                "claim_count": 1,
                "claims": [
                    {
                        "claim_id": "C1",
                        "docs_path": "docs/not-allowed.md",
                        "evidence": {"code_path": "pkg/sql/parsers/parser.go", "reason": "changed"},
                    }
                ],
            },
            "evidence_map": {},
        },
    )
    client = TestClient(app)
    response = client.post(
        "/invoke",
        json={
            "role": "author",
            "payload": {"diff": "x"},
            "model": {"provider": "anthropic", "name": "MiniMax-M2.5"},
            "system_prompt": "author prompt",
        },
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "invalid author response: claim.docs_path outside whitelist"


def test_invoke_author_rejects_patch_path_outside_whitelist(monkeypatch):
    monkeypatch.setenv("MCP_GATEWAY_MOCK", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.mcp_gateway.server._call_anthropic_json",
        lambda model, prompt: {
            "doc_patch_diff": (
                "diff --git a/docs/not-allowed.md b/docs/not-allowed.md\n"
                "@@ -1 +1 @@\n"
                "+x\n"
            ),
            "change_summary_md": "summary",
            "claims": {
                "claim_count": 1,
                "claims": [
                    {
                        "claim_id": "C1",
                        "docs_path": "docs/sql-reference/sql-syntax.md",
                        "evidence": {"code_path": "pkg/sql/parsers/parser.go", "reason": "changed"},
                    }
                ],
            },
            "evidence_map": {},
        },
    )
    client = TestClient(app)
    response = client.post(
        "/invoke",
        json={
            "role": "author",
            "payload": {"diff": "x"},
            "model": {"provider": "anthropic", "name": "MiniMax-M2.5"},
            "system_prompt": "author prompt",
        },
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "invalid author response: patch path outside whitelist"


def test_invoke_author_rejects_empty_patch_for_substantive_evidence(monkeypatch):
    monkeypatch.setenv("MCP_GATEWAY_MOCK", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.mcp_gateway.server._call_anthropic_json",
        lambda model, prompt: {
            "doc_patch_diff": "",
            "change_summary_md": "summary",
            "claims": {"claim_count": 1, "claims": [{"claim_id": "C1", "docs_path": "docs/sql-reference/sql-syntax.md", "evidence": {"code_path": "pkg/sql/parsers/parser.go", "reason": "changed"}}]},
            "evidence_map": {},
        },
    )
    client = TestClient(app)
    response = client.post(
        "/invoke",
        json={
            "role": "author",
            "payload": {"evidence_bundle": {"retrieval_scope": [{"code_path_prefix": "pkg/sql/parsers", "in_scope": True}]}},
            "model": {"provider": "anthropic", "name": "MiniMax-M2.5"},
            "system_prompt": "author prompt",
        },
    )
    assert response.status_code == 502
    assert (
        response.json()["detail"]
        == "invalid author response: non-empty doc_patch_diff is required for substantive evidence"
    )


def test_invoke_author_allows_empty_patch_when_no_in_scope_mapping(monkeypatch):
    monkeypatch.setenv("MCP_GATEWAY_MOCK", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(
        "app.mcp_gateway.server._call_anthropic_json",
        lambda model, prompt: {
            "doc_patch_diff": "",
            "change_summary_md": "no doc update",
            "claims": {"claim_count": 0, "claims": []},
            "evidence_map": {},
        },
    )
    client = TestClient(app)
    response = client.post(
        "/invoke",
        json={
            "role": "author",
            "payload": {"evidence_bundle": {"retrieval_scope": [{"in_scope": False}]}},
            "model": {"provider": "anthropic", "name": "MiniMax-M2.5"},
            "system_prompt": "author prompt",
        },
    )
    assert response.status_code == 200
