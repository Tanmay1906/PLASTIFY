"""PLASTIFY SENTINEL Base Detector Interface."""

from abc import ABC, abstractmethod
import logging
from typing import List

from app.schemas.sentinel import SentinelFlagCreate
from app.services.sentinel.context import SentinelContext

logger = logging.getLogger("plastify.sentinel.detectors")


class BaseSentinelDetector(ABC):
    """Abstract base class for all pluggable Sentinel anomaly detectors."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifying name for the detector."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable explanation of the detector's domain and heuristic."""
        pass

    @abstractmethod
    async def evaluate(self, context: SentinelContext) -> List[SentinelFlagCreate]:
        """Execute risk analysis against the provided context and return detected flags."""
        pass
