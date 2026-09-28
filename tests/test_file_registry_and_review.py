from __future__ import annotations

from fastapi.testclient import TestClient

from qiaowenshu_agent.api import create_app
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.files import ProjectFileRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.skills import build_default_registry
from qiaowenshu_agent.skills.consistency_review import ConsistencyReviewSkill
from qiaowenshu_agent.skills.quotation_check import QuotationCheckSkill
from qiaowenshu_agent.skills.requirement_ledger import RequirementLedgerSkill


def test_file_registry_deduplicates_and_versions_changed_files() -> None:
    registry = ProjectFileRegistry()
    first = registry.register(
        project_id="project-1",
        file_name="tender.txt",
        file_role="tender",
        content="第一版".encode(),
    )
    duplicate = registry.register(
        project_id="project-1",
        file_name="renamed.txt",
        file_role="tender",
        content="第一版".encode(),
    )
    second = registry.register(
        project_id="project-1",
        file_name="tender.txt",
        file_role="tender",
        content="第二版".encode(),
    )

    assert duplicate.deduplicated is True
    assert duplicate.file.file_id == first.file.file_id
    assert second.file.version == 2
    assert second.file.supersedes == first.file.file_id
    artifact = registry.parse(second.file.file_id)
    assert artifact["text"] == "第二版"
    assert registry.require(second.file.file_id).parse_status == "success"


async def _run_skill(skill, payload):
    from qiaowenshu_agent.core.context import SkillContext

    request = SkillRequest.create(payload)
    return await skill.execute(
        request,
        SkillContext(run_id="run-test", request=request),
    )


def test_consistency_review_and_quotation_check_are_rule_based() -> None:
    import asyncio

    consistency = asyncio.run(
        _run_skill(
            ConsistencyReviewSkill(),
            {
                "documents": [
                    {
                        "document_id": "commercial",
                        "text": (
                            "项目名称：数据平台\n项目工期：90日历天\n投标总价：950000"
                        ),
                    },
                    {
                        "document_id": "technical",
                        "text": (
                            "项目名称：数据平台\n项目工期：120日历天\n投标总价：950000"
                        ),
                    },
                ]
            },
        )
    )
    assert consistency.status == "success"
    assert consistency.data["summary"]["conflict_count"] == 1
    assert consistency.data["conflicts"][0]["field"] == "project_duration"

    quotation = asyncio.run(
        _run_skill(
            QuotationCheckSkill(),
            {
                "total_price": "100.00",
                "line_items": [
                    {"name": "A", "quantity": 2, "unit_price": 30},
                    {"name": "B", "quantity": 1, "unit_price": 40},
                ],
                "quoted_totals": [{"document_id": "quotation-letter", "value": 100}],
                "price_ceiling": 120,
            },
        )
    )
    assert quotation.status == "success"
    assert quotation.data["summary"]["failed_count"] == 0


def test_requirement_ledger_joins_evidence_and_response_location() -> None:
    import asyncio

    result = asyncio.run(
        _run_skill(
            RequirementLedgerSkill(),
            {
                "project_id": "project-1",
                "requirements": [
                    {
                        "requirement_id": "Q-001",
                        "category": "qualification",
                        "title": "营业执照",
                        "description": "提供有效营业执照",
                        "mandatory": True,
                        "evidence_required": ["business_license"],
                    }
                ],
                "evidence_matches": [
                    {
                        "requirement_id": "Q-001",
                        "material_id": "file-license",
                        "status": "matched",
                    }
                ],
                "response_map": {"Q-001": "资格文件 3.2"},
            },
        )
    )
    assert result.status == "success"
    entry = result.data["entries"][0]
    assert entry["status"] == "matched"
    assert entry["evidence_material_ids"] == ["file-license"]
    assert entry["response_location"] == "资格文件 3.2"


def test_file_backed_runtime_reaches_bidder_profile_and_ledger() -> None:
    registry = ProjectFileRegistry()
    tender = registry.register(
        project_id="project-1",
        file_name="招标文件.txt",
        file_role="tender",
        content=(
            "项目名称：数据治理平台\n"
            "项目编号：T-001\n"
            "资格要求：须提供有效营业执照。\n"
            "项目工期：90日历天\n"
            "技术方案 10分。\n"
        ).encode(),
    )
    license_file = registry.register(
        project_id="project-1",
        file_name="营业执照.txt",
        file_role="bidder_material",
        material_type="business_license",
        content="企业名称：测试科技有限公司\n营业执照：有效".encode(),
    )
    runtime = AgentRuntime(
        build_default_registry(file_registry=registry),
        services={"file_registry": registry},
    )

    import asyncio

    result = asyncio.run(
        runtime.run(
            SkillRequest.create(
                {
                    "project_id": "project-1",
                    "file_ids": [tender.file.file_id],
                    "bidder_file_ids": [license_file.file.file_id],
                    "bidder_id": "bidder-1",
                    "bidder_name": "测试科技有限公司",
                    "task": "这个项目能不能投？",
                }
            )
        )
    )
    assert result.status == "partial"
    assert [step.skill_name for step in result.steps] == [
        "document-preprocess",
        "tender-intake",
        "consistency-review",
        "tender-decomposition",
        "bidder-material-intake",
        "evidence-matching",
        "bid-feasibility",
        "requirement-ledger",
        "compliance-review",
        "scoring-strategy",
        "analysis-report",
    ]
    assert result.steps[4].result.data["summary"]["material_count"] == 1
    assert result.steps[-4].result.data["summary"]["entry_count"] >= 1
    assert result.steps[-1].result.data["summary"]["finding_count"] >= 1


def test_file_api_registers_lists_and_exposes_extended_skill_catalog() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/v1/projects/project-1/files?file_name=tender.txt&file_role=tender",
        content="项目名称：测试项目\n资格要求：须提供有效营业执照。".encode(),
    )
    assert response.status_code == 200
    file_id = response.json()["file"]["file_id"]
    multipart = client.post(
        "/v1/projects/project-1/files?file_role=other",
        files={"file": ("notes.txt", b"multipart content")},
    )
    assert multipart.status_code == 200
    assert multipart.json()["file"]["file_name"] == "notes.txt"
    listed = client.get("/v1/projects/project-1/files")
    assert listed.status_code == 200
    assert file_id in {item["file_id"] for item in listed.json()["files"]}
    preprocess = client.post(
        "/v1/agent/runs",
        json={
            "skill_name": "document-preprocess",
            "input": {
                "file_id": file_id,
                "business_scene": "tender_parse",
            },
        },
    )
    assert preprocess.status_code == 200
    assert preprocess.json()["status"] == "success"
    assert preprocess.json()["output"]["parse_ready_file_id"] == file_id
    material_response = client.post(
        "/v1/projects/project-1/files?file_name=license.txt&file_role=bidder_material",
        content="企业名称：测试企业\n营业执照：有效".encode(),
    )
    material_id = material_response.json()["file"]["file_id"]
    analysis = client.post(
        "/v1/projects/project-1/analyze",
        json={
            "file_ids": [file_id],
            "bidder_file_ids": [material_id],
            "bidder_id": "bidder-1",
        },
    )
    assert analysis.status_code == 200
    assert analysis.json()["steps"][-3]["skill_name"] == "compliance-review"
    assert analysis.json()["steps"][-1]["skill_name"] == "analysis-report"
    catalog = client.get("/v1/skills?include_extended=true")
    names = {item["name"] for item in catalog.json()["skills"]}
    assert {"bidder-material-intake", "requirement-ledger", "quotation-check"} <= names
