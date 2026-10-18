"""PLASTIFY SENTINEL External Integrations & Abstractions."""

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

__all__ = [
    "BaseOCRService",
    "RuleBasedOCRService",
    "BaseVisionService",
    "MockVisionService",
    "BaseImageSimilarityService",
    "DifferenceHashSimilarityService",
    "BaseAnomalyModelService",
    "HeuristicAnomalyModelService",
]
