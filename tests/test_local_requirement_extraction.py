from pathlib import Path

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.files import ProjectFileRegistry
from qiaowenshu_agent.skills.local_backends import (
    RegistryTenderDecompositionBackend,
)


def _context() -> SkillContext:
    return SkillContext(
        run_id="local-requirement-extraction",
        request=SkillRequest.create(),
    )


def _reference(document_id: str, page: int, version: str, quote: str) -> dict:
    return {
        "document_id": document_id,
        "page": page,
        "source_version": version,
        "quote": quote,
        "locator": f"{document_id}:p{page}",
    }


def _extract(sections: list[dict]) -> dict:
    return RegistryTenderDecompositionBackend().run(
        {"sections": sections},
        _context(),
    )


def test_six_high_risk_omissions_are_kept_as_complete_mandatory_clauses() -> None:
    content = (
        "1. 在中华人民共和国境内依法登记，提供有效营业执照或法人登记证明。\n"
        "2. 提供2025年度审计报告关键页或银行资信证明。\n"
        "3. 拟任项目经理须持有信息系统项目管理师证书，并提供投标人为其连续缴纳"
        "2026年3月至\n"
        "8月社会保险的证明。\n"
        "4. 支持与采购人现有统一身份平台通过OAuth2.0/OIDC\n"
        "对接；不得要求更换现有身份系统。\n"
        "5. 敏感字段传输须采用TLS1.2\n"
        "及以上；数据库敏感字段支持国密算法或等效强度加密。\n"
        "6. 应支持采购人现有国产Linux、PostgreSQL\n"
        "兼容数据库环境，不得绑定单一公有云。"
    )
    result = _extract(
        [
            {
                "title": "招标文件.pdf",
                "content": content,
                "source_references": [
                    _reference("招标文件.pdf", 1, "招标文件.pdf:v1", content)
                ],
            }
        ]
    )

    descriptions = [item["description"] for item in result["requirements"]]
    assert any("营业执照或法人登记证明" in text for text in descriptions)
    assert any("审计报告关键页或银行资信证明" in text for text in descriptions)
    manager = next(text for text in descriptions if "项目经理" in text)
    assert "信息系统项目管理师" in manager
    assert "2026年3月至 8月社会保险" in manager
    identity = next(text for text in descriptions if "OAuth2.0/OIDC" in text)
    assert "不得要求更换现有身份系统" in identity
    encryption = next(text for text in descriptions if "TLS1.2" in text)
    assert "国密算法或等效强度加密" in encryption
    deployment = next(text for text in descriptions if "国产Linux" in text)
    assert "PostgreSQL 兼容数据库环境" in deployment
    assert all(item["mandatory"] for item in result["requirements"])
    assert result["extraction_complete"] is False
    assert result["needs_human_review"] is True
    assert result["business_status"] == "needs_review"


def test_cross_page_join_keeps_actual_fragments_and_line_locators() -> None:
    result = _extract(
        [
            {
                "title": "招标文件.pdf",
                "content": "支持与现有身份平台通过 OAuth2.0/OIDC\f"
                "对接；不得要求更换现有身份系统。",
                "source_references": [
                    _reference(
                        "招标文件.pdf",
                        1,
                        "招标文件.pdf:v1",
                        "页首无关内容",
                    ),
                    _reference(
                        "招标文件.pdf",
                        2,
                        "招标文件.pdf:v1",
                        "另一页无关内容",
                    ),
                ],
            }
        ]
    )
    requirement = result["requirements"][0]
    assert "OAuth2.0/OIDC 对接" in requirement["description"]
    references = requirement["source_references"]
    assert {item["page"] for item in references} == {1, 2}
    assert all(item["quote"] != "页首无关内容" for item in references)
    assert all(":l" in item["locator"] for item in references)


def test_unrelated_adjacent_narrative_is_not_joined() -> None:
    result = _extract(
        [
            {
                "title": "招标文件.pdf",
                "content": "平台建设目标为提升数据治理能力\n"
                "采购人具有独立法人资格。",
                "source_references": [
                    _reference(
                        "招标文件.pdf",
                        1,
                        "招标文件.pdf:v1",
                        "平台建设目标为提升数据治理能力",
                    )
                ],
            }
        ]
    )
    assert len(result["requirements"]) == 0


def test_same_clause_from_different_versions_keeps_both_sources() -> None:
    clause = "投标人应提供有效营业执照。"
    result = _extract(
        [
            {
                "title": "招标文件-v1.pdf",
                "content": clause,
                "source_references": [
                    _reference("招标文件.pdf", 1, "v1", clause)
                ],
            },
            {
                "title": "招标文件-v2.pdf",
                "content": clause,
                "source_references": [
                    _reference("招标文件.pdf", 1, "v2", clause)
                ],
            },
        ]
    )
    assert len(result["requirements"]) == 2
    assert {
        item["source_references"][0]["source_version"]
        for item in result["requirements"]
    } == {
        "v1",
        "v2",
    }


def test_real_registry_pdf_keeps_page_five_clauses_around_layout_noise() -> None:
    source = (
        Path(__file__).parent
        / "标书Agent全流程模拟测试包_v1"
        / "01_招标文件_政务数据治理平台建设项目_模拟.pdf"
    )
    registry = ProjectFileRegistry()
    registration = registry.register_path(project_id="real-pdf", path=source)
    artifact = registry.parse(registration.file.file_id)
    result = _extract(
        [
            {
                "title": artifact["file_name"],
                "content": artifact["text"],
                "source_references": [
                    reference
                    for page in artifact["pages"]
                    for reference in page["source_references"]
                ],
            }
        ]
    )

    descriptions = [item["description"] for item in result["requirements"]]
    identity = next(text for text in descriptions if "OAuth2.0/OIDC" in text)
    assert "对接" in identity
    assert "料" not in identity
    assert "资" not in identity
    encryption = next(text for text in descriptions if "TLS1.2" in text)
    assert "及以上" in encryption
    assert "拟" not in encryption
    deployment = next(text for text in descriptions if "PostgreSQL" in text)
    assert "兼容数据库环境" in deployment
    assert "部署兼容" not in deployment

    manager = next(text for text in descriptions if "信息系统项目管理师" in text)
    assert "2026 年 3 月至 8 月社会保险" in manager
    bond = next(text for text in descriptions if "投标保证金" in text)
    assert "40,000 元" in bond
    log = next(text for text in descriptions if "日志保存" in text)
    assert "180 天" in log

    assert all(
        reference["quote"] == reference["quote"].strip()
        for item in result["requirements"]
        for reference in item["source_references"]
    )
    assert not any(
        item["description"] == "申请人的资格要求"
        for item in result["requirements"]
    )


def test_real_pdf_six_requirement_families_use_manual_review_rules() -> None:
    source = (
        Path(__file__).parent
        / "标书Agent全流程模拟测试包_v1"
        / "01_招标文件_政务数据治理平台建设项目_模拟.pdf"
    )
    registry = ProjectFileRegistry()
    registration = registry.register_path(project_id="rule-integration", path=source)
    artifact = registry.parse(registration.file.file_id)
    result = _extract(
        [
            {
                "title": artifact["file_name"],
                "content": artifact["text"],
                "source_references": [
                    reference
                    for page in artifact["pages"]
                    for reference in page["source_references"]
                ],
            }
        ]
    )

    families = (
        ("营业执照", "法人登记证明"),
        ("审计报告关键页", "银行资信证明"),
        ("信息系统项目管理师", "社会保险"),
        ("OAuth2.0/OIDC", "不得要求更换现有身份系统"),
        ("TLS1.2", "国密算法或等效强度加密"),
        ("国产Linux", "PostgreSQL"),
    )
    for terms in families:
        requirement = next(
            item
            for item in result["requirements"]
            if all(
                term.replace(" ", "") in item["description"].replace(" ", "")
                for term in terms
            )
        )
        assert requirement["check_rule"]["rule_ast"]["op"] == "manual_review"

    iso_result = _extract(
        [
            {
                "title": "iso.txt",
                "content": "投标人须提供有效ISO/IEC 27001认证",
            }
        ]
    )
    assert iso_result["requirements"][0]["check_rule"] == {
        "rule_ast": {
            "op": "exists",
            "evidence_types": ["ISO27001"],
            "where": {"verification_status": "verified"},
        }
    }


def test_qualification_evidence_context_does_not_promote_background_text() -> None:
    result = _extract(
        [
            {
                "title": "requirements.txt",
                "content": (
                    "可选材料：投标人可以提交营业执照或法人登记证明作为背景资料，"
                    "不作为资格审查条件。\n"
                    "企业介绍：本公司取得法人登记证明并开展业务。\n"
                    "资格要求：提供有效营业执照或法人登记证明。\n"
                    "提供2025年度审计报告关键页或银行资信证明。\n"
                    "投标人可任选营业执照或法人登记证明其一提交。"
                ),
            }
        ]
    )

    descriptions = [item["description"] for item in result["requirements"]]
    assert not any("背景资料" in text for text in descriptions)
    assert not any("本公司取得法人登记证明" in text for text in descriptions)
    assert any("提供有效营业执照或法人登记证明" in text for text in descriptions)
    assert any("审计报告关键页或银行资信证明" in text for text in descriptions)
    assert any("可任选营业执照或法人登记证明其一提交" in text for text in descriptions)


def test_hard_submission_with_enterprise_description_is_kept() -> None:
    result = _extract(
        [
            {
                "title": "requirements.txt",
                "content": (
                    "投标人必须提交有效营业执照并附企业介绍。\n"
                    "投标人须提供有效法人登记证明及背景资料。\n"
                    "投标人应提交有效营业执照并附企业介绍。"
                ),
            }
        ]
    )

    descriptions = [item["description"] for item in result["requirements"]]
    assert any("必须提交有效营业执照" in text for text in descriptions)
    assert any("须提供有效法人登记证明" in text for text in descriptions)
    assert any("应提交有效营业执照" in text for text in descriptions)
