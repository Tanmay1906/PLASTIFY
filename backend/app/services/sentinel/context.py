"""PLASTIFY SENTINEL Evaluation Context."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from app.models.custody import ChainOfCustodyEvent
from app.models.evidence import Evidence
from app.models.logistics import Delivery, DeliveryEvidence, LogisticsAssignment
from app.models.organization import Organization
from app.models.program import Program
from app.models.recovery import RecoveryEvent
from app.models.user import User
from app.integrations.sentinel.ocr import BaseOCRService, RuleBasedOCRService
from app.integrations.sentinel.vision import BaseVisionService, MockVisionService
from app.integrations.sentinel.similarity import (
    BaseImageSimilarityService,
    DifferenceHashSimilarityService,
)
from app.integrations.sentinel.ml import (
    BaseAnomalyModelService,
    HeuristicAnomalyModelService,
)


@dataclass
class SentinelContext:
    """Holistic data bundle passed to Sentinel detectors for risk evaluation."""

    recovery: RecoveryEvent
    program: Optional[Program] = None
    collector: Optional[User] = None
    collector_organization: Optional[Organization] = None
    collection_evidence: List[Evidence] = field(default_factory=list)
    assignment: Optional[LogisticsAssignment] = None
    delivery: Optional[Delivery] = None
    delivery_evidence: List[DeliveryEvidence] = field(default_factory=list)
    custody_events: List[ChainOfCustodyEvent] = field(default_factory=list)
    historical_recoveries: List[RecoveryEvent] = field(default_factory=list)
    cross_recovery_evidence: List[Evidence] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)

    # Integration Services
    similarity_service: BaseImageSimilarityService = field(
        default_factory=DifferenceHashSimilarityService
    )
    ocr_service: BaseOCRService = field(default_factory=RuleBasedOCRService)
    vision_service: BaseVisionService = field(default_factory=MockVisionService)
    ml_service: BaseAnomalyModelService = field(default_factory=HeuristicAnomalyModelService)
