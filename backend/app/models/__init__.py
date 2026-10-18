"""PLASTIFY Models Package.

Re-exports Base and all entity models so Alembic autogenerate discovers them.
"""

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.audit import SystemAuditLog
from app.models.user import RefreshToken, User, UserRole
from app.models.organization import (
    Organization,
    OrganizationMember,
    OrganizationType,
    OrgMemberRole,
    PartnerRelationship,
    PartnerStatus,
)
from app.models.program import (
    PlasticMaterialType,
    Program,
    ProgramPartner,
    ProgramStatus,
)
from app.models.recovery import (
    RecoveryEvent,
    RecoveryEventHistory,
    RecoverySequence,
    RecoveryStatus,
)
from app.models.evidence import Evidence, EvidenceType
from app.models.custody import ChainOfCustodyEvent, CustodyState
from app.models.logistics import (
    AssignmentStatus,
    Delivery,
    DeliveryEvidence,
    DeliveryStatus,
    LogisticsAssignment,
    WeightToleranceStatus,
)
from app.models.verification import (
    FindingCategory,
    FindingSeverity,
    VerificationDecision,
    VerificationFinding,
    VerificationRecord,
)
from app.models.sentinel import (
    RiskLevel,
    SentinelFlag,
    SentinelResult,
    SentinelStatus,
)
from app.models.circular import (
    MaterialBatch,
    MaterialBatchEvidence,
    MaterialBatchItem,
    MaterialBatchStatus,
    MaterialPassport,
    Product,
    ProductPassport,
    UpcyclingAllocation,
    UpcyclingBatch,
    UpcyclingBatchEvidence,
    UpcyclingBatchStatus,
)
from app.models.impact import (
    AssessmentStatus,
    EligibilityAssessment,
    ImpactAllocation,
    ImpactOutcomeType,
    ImpactRecord,
    ImpactStatus,
    Methodology,
    MethodologyVersion,
)
from app.models.credit import (
    CreditBatch,
    CreditBatchStatus,
    CreditRetirement,
    CreditStatus,
    CreditTransaction,
    PlasticCredit,
    TransactionType,
)

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "SystemAuditLog",
    "User",
    "UserRole",
    "RefreshToken",
    "Organization",
    "OrganizationType",
    "OrganizationMember",
    "OrgMemberRole",
    "PartnerRelationship",
    "PartnerStatus",
    "PlasticMaterialType",
    "Program",
    "ProgramPartner",
    "ProgramStatus",
    "RecoveryEvent",
    "RecoveryEventHistory",
    "RecoverySequence",
    "RecoveryStatus",
    "Evidence",
    "EvidenceType",
    "ChainOfCustodyEvent",
    "CustodyState",
    "LogisticsAssignment",
    "Delivery",
    "DeliveryEvidence",
    "AssignmentStatus",
    "DeliveryStatus",
    "WeightToleranceStatus",
    "VerificationRecord",
    "VerificationFinding",
    "VerificationDecision",
    "FindingSeverity",
    "FindingCategory",
    "SentinelResult",
    "SentinelFlag",
    "RiskLevel",
    "SentinelStatus",
    "MaterialBatch",
    "MaterialBatchItem",
    "MaterialBatchEvidence",
    "MaterialBatchStatus",
    "MaterialPassport",
    "UpcyclingBatch",
    "UpcyclingAllocation",
    "UpcyclingBatchEvidence",
    "UpcyclingBatchStatus",
    "Product",
    "ProductPassport",
    "ImpactOutcomeType",
    "ImpactStatus",
    "AssessmentStatus",
    "Methodology",
    "MethodologyVersion",
    "ImpactRecord",
    "ImpactAllocation",
    "EligibilityAssessment",
    "CreditBatchStatus",
    "CreditStatus",
    "TransactionType",
    "CreditBatch",
    "PlasticCredit",
    "CreditTransaction",
    "CreditRetirement",
]
