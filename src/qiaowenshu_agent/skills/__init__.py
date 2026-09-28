"""Built-in skill implementations and registry factory."""

from qiaowenshu_agent.core.registry import SkillRegistry
from qiaowenshu_agent.skills.bid_feasibility.skill import BidFeasibilitySkill
from qiaowenshu_agent.skills.bidder_material_intake import BidderMaterialIntakeSkill
from qiaowenshu_agent.skills.analysis_report import AnalysisReportSkill
from qiaowenshu_agent.skills.compliance_review import ComplianceReviewSkill
from qiaowenshu_agent.skills.consistency_review import ConsistencyReviewSkill
from qiaowenshu_agent.skills.document_preprocess.skill import DocumentPreprocessSkill
from qiaowenshu_agent.skills.document_profile.skill import DocumentProfileSkill
from qiaowenshu_agent.skills.document_writing import DocumentWritingSkill
from qiaowenshu_agent.skills.evidence_matching.skill import EvidenceMatchingSkill
from qiaowenshu_agent.skills.knowledge_retrieval.ragflow_backend import (
    RagFlowRetrievalBackend,
)
from qiaowenshu_agent.skills.knowledge_retrieval.skill import KnowledgeRetrievalSkill
from qiaowenshu_agent.skills.scoring_strategy.skill import ScoringStrategySkill
from qiaowenshu_agent.skills.tender_decomposition.skill import (
    TenderDecompositionSkill,
)
from qiaowenshu_agent.skills.tender_intake.skill import TenderIntakeSkill
from qiaowenshu_agent.skills.quotation_check import QuotationCheckSkill
from qiaowenshu_agent.skills.requirement_ledger import RequirementLedgerSkill
from qiaowenshu_agent.skills.local_backends import (
    RegistryBidderMaterialBackend,
    RegistryDocumentPreprocessBackend,
    RegistryTenderDecompositionBackend,
    RegistryTenderIntakeBackend,
)
from qiaowenshu_agent.llm import OpenAICompatibleQwenClient


def build_default_registry(
    *,
    document_profile_backend=None,
    knowledge_retrieval_backend=None,
    document_preprocess_backend=None,
    tender_intake_backend=None,
    tender_decomposition_backend=None,
    bidder_material_backend=None,
    file_registry=None,
    llm_client=None,
) -> SkillRegistry:
    """Build an explicit registry; backends may be injected or loaded from env."""

    if knowledge_retrieval_backend is None:
        knowledge_retrieval_backend = RagFlowRetrievalBackend.from_env()
    if llm_client is None:
        llm_client = OpenAICompatibleQwenClient.from_env()
    if file_registry is not None:
        if document_preprocess_backend is None:
            document_preprocess_backend = RegistryDocumentPreprocessBackend(
                file_registry
            )
        if tender_intake_backend is None:
            tender_intake_backend = RegistryTenderIntakeBackend(file_registry)
        if tender_decomposition_backend is None:
            tender_decomposition_backend = RegistryTenderDecompositionBackend()
        if bidder_material_backend is None:
            bidder_material_backend = RegistryBidderMaterialBackend(file_registry)
    else:
        if tender_intake_backend is None:
            tender_intake_backend = RegistryTenderIntakeBackend()
        if tender_decomposition_backend is None:
            tender_decomposition_backend = RegistryTenderDecompositionBackend()

    registry = SkillRegistry()
    registry.register(AnalysisReportSkill())
    registry.register(BidFeasibilitySkill())
    registry.register(BidderMaterialIntakeSkill(backend=bidder_material_backend))
    registry.register(ComplianceReviewSkill())
    registry.register(ConsistencyReviewSkill())
    registry.register(DocumentProfileSkill(backend=document_profile_backend))
    registry.register(DocumentWritingSkill(llm=llm_client))
    registry.register(EvidenceMatchingSkill())
    registry.register(KnowledgeRetrievalSkill(backend=knowledge_retrieval_backend))
    registry.register(DocumentPreprocessSkill(backend=document_preprocess_backend))
    registry.register(ScoringStrategySkill())
    registry.register(QuotationCheckSkill())
    registry.register(RequirementLedgerSkill())
    registry.register(TenderDecompositionSkill(backend=tender_decomposition_backend))
    registry.register(TenderIntakeSkill(backend=tender_intake_backend))
    return registry


__all__ = [
    "AnalysisReportSkill",
    "BidFeasibilitySkill",
    "BidderMaterialIntakeSkill",
    "ComplianceReviewSkill",
    "ConsistencyReviewSkill",
    "DocumentPreprocessSkill",
    "DocumentProfileSkill",
    "DocumentWritingSkill",
    "EvidenceMatchingSkill",
    "KnowledgeRetrievalSkill",
    "RagFlowRetrievalBackend",
    "ScoringStrategySkill",
    "QuotationCheckSkill",
    "RequirementLedgerSkill",
    "TenderDecompositionSkill",
    "TenderIntakeSkill",
    "build_default_registry",
]
