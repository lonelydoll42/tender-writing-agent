from __future__ import annotations

from typing import Any


REQUIREMENTS: list[dict[str, Any]] = [
    {
        "requirement_id": "dq-bond",
        "category": "disqualification",
        "title": "投标保证金",
        "description": "按招标文件要求提交投标保证金100000元。",
        "mandatory": True,
        "evidence_required": ["bid_bond"],
        "check_rule": {
            "type": "bid_bond",
            "attribute": "bid_bond_amount",
            "minimum": 100000,
        },
        "source_references": [
            {
                "document_id": "benchmark-tender.pdf",
                "page": 6,
                "section": "废标条款",
                "quote": "未提交投标保证金的，投标无效。",
            }
        ],
    },
    {
        "requirement_id": "qual-license",
        "category": "qualification",
        "title": "营业执照",
        "description": "投标人应具有有效营业执照。",
        "mandatory": True,
        "evidence_required": ["business_license"],
    },
    {
        "requirement_id": "qual-iso",
        "category": "qualification",
        "title": "ISO27001认证",
        "description": "投标人应提供有效的ISO27001认证证书。",
        "mandatory": True,
        "evidence_required": ["ISO27001"],
    },
    {
        "requirement_id": "qual-case",
        "category": "qualification",
        "title": "类似项目案例",
        "description": "近三年应具有不少于2个类似项目案例。",
        "mandatory": True,
        "check_rule": {
            "type": "similar_case",
            "attribute": "similar_case_count",
            "minimum": 2,
        },
    },
    {
        "requirement_id": "qual-person",
        "category": "qualification",
        "title": "项目负责人证书",
        "description": "项目负责人应具备项目管理相关证书。",
        "mandatory": True,
        "evidence_required": ["personnel_certificate"],
    },
    {
        "requirement_id": "tech-backup",
        "category": "technical",
        "title": "数据备份能力",
        "description": "系统应支持数据备份。",
        "mandatory": True,
        "check_rule": {
            "type": "technical_parameter",
            "attribute": "technical_parameters.data_backup",
            "expected": True,
        },
    },
]

COMPLETE_BIDDER: dict[str, Any] = {
    "bidder_id": "benchmark-bidder",
    "bidder_name": "测试企业",
    "attributes": {
        "bid_bond_amount": 100000,
        "similar_case_count": 3,
        "technical_parameters": {"data_backup": True},
    },
    "materials": [
        {
            "material_id": "mat-license",
            "material_type": "business_license",
            "title": "营业执照",
        },
        {
            "material_id": "mat-iso",
            "material_type": "certification",
            "title": "ISO27001认证证书",
        },
        {
            "material_id": "mat-person",
            "material_type": "personnel_certificate",
            "title": "项目负责人证书",
        },
        {
            "material_id": "mat-bond",
            "material_type": "bid_bond",
            "title": "投标保证金缴纳凭证",
        },
    ],
}

SCORING_TABLE: dict[str, Any] = {
    "columns": ["评分项", "分值", "评分标准"],
    "values": [
        [
            "项目实施方案",
            "10",
            (
                "方案完整、合理，包含项目组织、进度计划、风险管理、质量管理；"
                "需提供项目团队、甘特图、风险表、质量方案。"
            ),
        ],
        ["企业案例", "10", "每提供一个类似项目合同得5分，需提供合同和验收报告。"],
        ["报价", "30", "按照价格计算。"],
    ],
}

REGRESSION_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "TC01",
        "name": "正常政府采购项目",
        "focus": "完整前五节点",
        "supported": True,
    },
    {
        "id": "TC02",
        "name": "IT软件项目",
        "focus": "技术参数与方案评分",
        "supported": True,
    },
    {
        "id": "TC03",
        "name": "隐藏废标条件",
        "focus": "硬性条件召回与失败结论",
        "supported": True,
    },
    {
        "id": "TC04",
        "name": "资质不足",
        "focus": "缺失ISO27001材料不得通过",
        "supported": True,
    },
    {
        "id": "TC05",
        "name": "复杂评分标准",
        "focus": "评分项、证据和优先级",
        "supported": True,
    },
    {
        "id": "TC06",
        "name": "大量技术参数",
        "focus": "结构化技术要求",
        "supported": True,
    },
    {
        "id": "TC07",
        "name": "缺少公司资料",
        "focus": "unknown/human_review",
        "supported": True,
    },
    {
        "id": "TC08",
        "name": "前后工期冲突",
        "focus": "跨文档一致性",
        "supported": True,
    },
    {
        "id": "TC09",
        "name": "报价不一致",
        "focus": "报价校验",
        "supported": True,
    },
    {
        "id": "TC10",
        "name": "完整标书生成",
        "focus": "目录、撰写、响应、审核和封装",
        "supported": False,
    },
)
