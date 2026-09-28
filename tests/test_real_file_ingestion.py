from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.files import ProjectFileRegistry
from qiaowenshu_agent.skills.local_backends import RegistryBidderMaterialBackend


FIXTURE_ROOT = Path(__file__).parent / "标书Agent全流程模拟测试包_v1"


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext is required")
def test_real_tender_pdf_creates_page_aware_artifact() -> None:
    source = next(FIXTURE_ROOT.glob("01_招标文件*.pdf"))
    registry = ProjectFileRegistry()
    registration = registry.register_path(
        project_id="SIM-2026-IT-017",
        path=source,
        file_role="tender",
    )

    artifact = registry.parse(registration.file.file_id)

    assert artifact["page_count"] >= 1
    assert "SIM-2026-IT-017" in artifact["text"]
    assert "投标截止" in artifact["text"]
    assert registration.file.checksum
    assert (
        registry.require(registration.file.file_id).parse_artifact_id
        == (artifact["artifact_id"])
    )


@pytest.mark.skipif(shutil.which("pdftotext") is None, reason="pdftotext is required")
def test_scanned_certificate_stays_unknown_without_ocr() -> None:
    source = next(FIXTURE_ROOT.glob("04A_ISO27001*.pdf"))
    registry = ProjectFileRegistry()
    registration = registry.register_path(
        project_id="SIM-2026-IT-017",
        path=source,
        file_role="bidder_material",
    )
    context = SkillContext(
        run_id="run-scan",
        request=SkillRequest.create(),
        services={"file_registry": registry},
    )

    result = RegistryBidderMaterialBackend().run(
        {
            "bidder_id": "bidder-1",
            "bidder_name": "",
            "file_ids": [registration.file.file_id],
            "materials": [],
        },
        context,
    )

    material = result["bidder_profile"]["materials"][0]
    assert material["material_type"] == "certification"
    assert material["metadata"]["verification_status"] == "unknown"
    assert result["warnings"]
