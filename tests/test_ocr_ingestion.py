from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qiaowenshu_agent.api import create_app
from qiaowenshu_agent.core import files as files_module
from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.files import ProjectFileRegistry
from qiaowenshu_agent.domain.models import SourceReference
from qiaowenshu_agent.skills.compliance_review import ComplianceReviewSkill
from qiaowenshu_agent.skills.bid_feasibility import BidFeasibilitySkill
from qiaowenshu_agent.skills.evidence_matching import EvidenceMatchingSkill
from qiaowenshu_agent.skills.requirement_ledger import RequirementLedgerSkill
from qiaowenshu_agent.skills.local_backends import RegistryBidderMaterialBackend


FIXTURE_ROOT = Path(__file__).parent / "标书Agent全流程模拟测试包_v1"
SCANNED_PDF = next(FIXTURE_ROOT.glob("04A_ISO27001*.pdf"))
POPPLER_AVAILABLE = all(
    shutil.which(name) or shutil.which(f"{name}.exe")
    for name in ("pdftotext", "pdftoppm")
)


class FakeOCR:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def run(self, payload: dict[str, object]) -> object:
        self.calls.append(payload)
        return self.response


@pytest.mark.skipif(
    not POPPLER_AVAILABLE,
    reason="Poppler pdftotext and pdftoppm are required",
)
def test_scanned_pdf_ocr_provenance_and_low_confidence_are_preserved() -> None:
    backend = FakeOCR(
        {
            "text": "ISO/IEC 27001认证有效",
            "confidence": 0.61,
            "regions": [{"bbox": [1, 2, 3, 4], "text": "ISO/IEC 27001"}],
        }
    )
    registry = ProjectFileRegistry(ocr_backend=backend)
    registration = registry.register_path(
        project_id="ocr-project",
        path=SCANNED_PDF,
        file_role="bidder_material",
    )

    artifact = registry.parse(registration.file.file_id)
    page = artifact["pages"][0]
    reference = page["source_references"][0]

    assert backend.calls
    assert page["extraction_method"] == "ocr"
    assert page["confidence"] == 0.61
    assert reference["bbox"] == [1.0, 2.0, 3.0, 4.0]
    assert reference["confidence"] == 0.61
    assert reference["source_version"] == f"{registration.file.file_id}:v1"


@pytest.mark.skipif(
    not POPPLER_AVAILABLE,
    reason="Poppler pdftotext and pdftoppm are required",
)
def test_ocr_without_confidence_requires_review_warning() -> None:
    backend = FakeOCR({"text": "OCR text without a score"})
    registry = ProjectFileRegistry(ocr_backend=backend)
    registration = registry.register_path(
        project_id="ocr-project",
        path=SCANNED_PDF,
        file_role="bidder_material",
    )

    artifact = registry.parse(registration.file.file_id)
    page = artifact["pages"][0]

    assert page["extraction_method"] == "ocr"
    assert page["confidence"] == 0.0
    assert any("no confidence" in item for item in page["warnings"])
    assert any("no confidence" in item for item in artifact["warnings"])


def test_mixed_page_combines_native_text_and_ocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeOCR({"text": "OCR table row", "confidence": 0.92})
    monkeypatch.setattr(files_module, "_pdf_page_count", lambda _content: 1)
    monkeypatch.setattr(
        files_module,
        "_pdf_pages_with_images",
        lambda _content: {1},
    )
    monkeypatch.setattr(
        files_module,
        "_extract_pdf_page_text",
        lambda _content, _page_number: "Native heading",
    )
    monkeypatch.setattr(
        files_module,
        "_render_pdf_page",
        lambda _content, _page_number: b"fake png",
    )
    registry = ProjectFileRegistry(ocr_backend=backend)
    registration = registry.register(
        project_id="mixed-project",
        file_name="mixed.pdf",
        file_role="tender",
        content=b"%PDF-1.4 fake",
    )

    artifact = registry.parse(registration.file.file_id)
    page = artifact["pages"][0]

    assert page["page_type"] == "mixed"
    assert page["extraction_method"] == "mixed"
    assert page["text"] == "Native heading\nOCR table row"
    assert page["confidence"] == 0.92


@pytest.mark.asyncio
async def test_low_confidence_evidence_flows_to_ledger_and_compliance() -> None:
    low_confidence_reference = SourceReference(
        document_id="scan.pdf",
        page=1,
        confidence=0.61,
        extraction_method="ocr",
    )
    request = SkillRequest.create(
        {
            "requirements": [
                {
                    "requirement_id": "license",
                    "category": "qualification",
                    "title": "营业执照",
                    "description": "提供有效营业执照",
                    "mandatory": True,
                    "evidence_required": ["business_license"],
                }
            ],
            "materials": [
                {
                    "material_id": "scan-license",
                    "material_type": "business_license",
                    "content": "企业营业执照有效",
                    "source_references": [low_confidence_reference.to_dict()],
                }
            ],
        },
        skill_name="evidence-matching",
    )
    context = SkillContext(run_id="ocr-review", request=request)
    matching = await EvidenceMatchingSkill().execute(request, context)

    match = matching.data["matches"][0]
    assert match["status"] == "human_review"
    assert match["confidence"] <= 0.61
    assert matching.data["summary"]["human_review_count"] == 1

    ledger_request = SkillRequest.create(
        {
            "project_id": "ocr-project",
            "requirements": request.input["requirements"],
            "evidence_matches": matching.data["matches"],
        },
        skill_name="requirement-ledger",
    )
    ledger = await RequirementLedgerSkill().execute(
        ledger_request,
        SkillContext(run_id="ocr-ledger", request=ledger_request),
    )
    entry = ledger.data["entries"][0]
    assert entry["status"] == "human_review"
    assert entry["gap_type"] == "human_review"
    assert ledger.data["summary"]["theoretical_score_coverage"] is None

    compliance_request = SkillRequest.create(
        {"project_id": "ocr-project", "ledger": ledger.data},
        skill_name="compliance-review",
    )
    compliance = await ComplianceReviewSkill().execute(
        compliance_request,
        SkillContext(run_id="ocr-compliance", request=compliance_request),
    )
    assert compliance.status == "partial"
    assert compliance.data["needs_human_review"] is True
    assert compliance.data["summary"]["high_risk_count"] == 1

    feasibility_request = SkillRequest.create(
        {
            "project_id": "ocr-project",
            "requirements": request.input["requirements"],
            "bidder_profile": {
                "bidder_id": "ocr-bidder",
                "materials": request.input["materials"],
            },
        },
        skill_name="bid-feasibility",
    )
    feasibility = await BidFeasibilitySkill().execute(
        feasibility_request,
        SkillContext(run_id="ocr-feasibility", request=feasibility_request),
    )
    assert feasibility.data["decision"] == "human_review"
    assert feasibility.data["checks"][0]["status"] == "unknown"


@pytest.mark.skipif(
    not POPPLER_AVAILABLE,
    reason="Poppler pdftotext and pdftoppm are required",
)
def test_api_injects_ocr_backend_for_file_parse() -> None:
    backend = FakeOCR({"text": "OCR API text", "confidence": 0.8})
    client = TestClient(create_app(ocr_backend=backend))
    uploaded = client.post(
        "/v1/projects/ocr-project/files?file_name=scan.pdf&file_role=other",
        content=SCANNED_PDF.read_bytes(),
    )
    assert uploaded.status_code == 200
    file_id = uploaded.json()["file"]["file_id"]

    parsed = client.post(f"/v1/projects/ocr-project/files/{file_id}/parse")
    assert parsed.status_code == 200
    page = parsed.json()["artifact"]["pages"][0]
    assert page["extraction_method"] == "ocr"
    assert page["confidence"] == 0.8
    assert backend.calls


def test_file_backed_materials_keep_all_page_references() -> None:
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id="pages-project",
        file_name="material.txt",
        file_role="bidder_material",
        content=b"page one\fpage two",
    )
    context = SkillContext(
        run_id="pages-material",
        request=SkillRequest.create(),
        services={"file_registry": registry},
    )

    result = RegistryBidderMaterialBackend().run(
        {
            "bidder_id": "bidder",
            "file_ids": [registration.file.file_id],
        },
        context,
    )
    references = result["bidder_profile"]["materials"][0]["source_references"]
    assert [item["page"] for item in references] == [1, 2]
