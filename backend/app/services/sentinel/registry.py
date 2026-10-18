"""PLASTIFY SENTINEL Pluggable Detector Registry."""

import asyncio
import logging
from typing import Dict, List, Type

from app.schemas.sentinel import SentinelFlagCreate
from app.services.sentinel.base import BaseSentinelDetector
from app.services.sentinel.context import SentinelContext
from app.services.sentinel.detectors.behavioral import BehavioralAnomalyDetector
from app.services.sentinel.detectors.delivery_mismatch import DeliveryMismatchDetector
from app.services.sentinel.detectors.duplicate_evidence import DuplicateEvidenceDetector
from app.services.sentinel.detectors.gps import GPSAnomalyDetector
from app.services.sentinel.detectors.timestamp import TimestampAnomalyDetector
from app.services.sentinel.detectors.weight import WeightAnomalyDetector

logger = logging.getLogger("plastify.sentinel.registry")


class SentinelDetectorRegistry:
    """Registry coordinating pluggable Sentinel anomaly detectors."""

    def __init__(self) -> None:
        self._detectors: Dict[str, BaseSentinelDetector] = {}
        # Register core initial detectors
        self.register(WeightAnomalyDetector())
        self.register(GPSAnomalyDetector())
        self.register(TimestampAnomalyDetector())
        self.register(DuplicateEvidenceDetector())
        self.register(DeliveryMismatchDetector())
        self.register(BehavioralAnomalyDetector())

    def register(self, detector: BaseSentinelDetector) -> None:
        """Register a new or custom anomaly detector."""
        self._detectors[detector.name] = detector
        logger.info(f"Registered Sentinel detector: {detector.name}")

    def unregister(self, detector_name: str) -> None:
        """Unregister a detector by name."""
        if detector_name in self._detectors:
            del self._detectors[detector_name]
            logger.info(f"Unregistered Sentinel detector: {detector_name}")

    def list_detectors(self) -> List[Dict[str, str]]:
        """List active detectors and descriptions."""
        return [
            {"name": d.name, "description": d.description}
            for d in self._detectors.values()
        ]

    async def run_all(self, context: SentinelContext) -> List[SentinelFlagCreate]:
        """Execute all registered detectors concurrently across the evaluation context."""
        flags: List[SentinelFlagCreate] = []

        async def _run_single(detector: BaseSentinelDetector) -> List[SentinelFlagCreate]:
            try:
                return await detector.evaluate(context)
            except Exception as exc:
                logger.error(
                    f"Error executing Sentinel detector '{detector.name}': {exc}",
                    exc_info=True,
                )
                return []

        # Run all detectors in parallel using asyncio.gather
        tasks = [_run_single(d) for d in self._detectors.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, list):
                flags.extend(res)

        return flags
