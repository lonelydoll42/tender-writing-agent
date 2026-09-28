from __future__ import annotations

from fastapi.testclient import TestClient

from qiaowenshu_agent.api import app


def test_skill_catalog_endpoint() -> None:
    client = TestClient(app)

    response = client.get("/v1/skills")

    assert response.status_code == 200
    assert {item["name"] for item in response.json()["skills"]} == {
        "bid-feasibility",
        "document-preprocess",
        "document-profile",
        "document-writing",
        "evidence-matching",
        "knowledge-retrieval",
        "scoring-strategy",
        "tender-decomposition",
        "tender-intake",
    }


def test_agent_endpoint_returns_typed_blocked_result() -> None:
    client = TestClient(app)

    response = client.post(
        "/v1/agent/runs",
        json={
            "skill_name": "document-preprocess",
            "input": {
                "file_id": "file_1",
                "business_scene": "tender_parse",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    assert response.json()["steps"][0]["result"]["error_code"] == (
        "PREPROCESS_BACKEND_NOT_CONFIGURED"
    )
