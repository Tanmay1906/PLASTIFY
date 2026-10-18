"""PLASTIFY SENTINEL Behavioral Anomaly Detector."""

from datetime import datetime, timezone
import logging
from typing import List

from app.models.sentinel import RiskLevel
from app.schemas.sentinel import SentinelFlagCreate
from app.services.sentinel.base import BaseSentinelDetector
from app.services.sentinel.context import SentinelContext

logger = logging.getLogger("plastify.sentinel.detectors.behavioral")


class BehavioralAnomalyDetector(BaseSentinelDetector):
    """Identifies synthetic submission patterns, repetitive identical values, and burst velocity."""

    @property
    def name(self) -> str:
        return "BehavioralAnomalyDetector"

    @property
    def description(self) -> str:
        return "Detects repetitive weights, clone coordinates, and abnormal submission frequency bursts."

    async def evaluate(self, context: SentinelContext) -> List[SentinelFlagCreate]:
        flags: List[SentinelFlagCreate] = []
        recovery = context.recovery
        history = context.historical_recoveries

        if not history:
            return flags

        # 1. Repetitive Identical Weights Pattern
        # Real-world post-consumer plastic collection has natural tare/moisture variance.
        # Repeatedly logging exact same floating weight (e.g. 100.00 kg 3+ times) is a strong synthetic indicator.
        same_collector_history = [
            h for h in history if h.collector_id == recovery.collector_id and h.id != recovery.id
        ]

        if same_collector_history and recovery.weight_kg > 0:
            matching_weights = [
                h for h in same_collector_history if abs(h.weight_kg - recovery.weight_kg) < 0.001
            ]
            if len(matching_weights) >= 2:  # 3 total occurrences including current
                flags.append(
                    SentinelFlagCreate(
                        detector=self.name,
                        severity=RiskLevel.HIGH if len(matching_weights) >= 4 else RiskLevel.MEDIUM,
                        reason=(
                            f"Repetitive weight signature: exact weight {recovery.weight_kg:.2f} kg has been "
                            f"repeated across {len(matching_weights) + 1} distinct collection events by this collector."
                        ),
                        confidence=0.88,
                        evidence_reference=str(recovery.id),
                        metadata={
                            "weight_kg": recovery.weight_kg,
                            "repetition_count": len(matching_weights) + 1,
                            "matching_event_ids": [str(m.id) for m in matching_weights[:5]],
                        },
                    )
                )

        # 2. Duplicate GPS Micro-Coordinates (Pinpoint Cloning)
        # Identical coordinates to 5 decimal places (~1 meter) across supposedly independent field sweeps
        cur_coords = recovery.collection_coordinates
        if cur_coords and "latitude" in cur_coords and "longitude" in cur_coords:
            cur_lat = round(float(cur_coords["latitude"]), 5)
            cur_lon = round(float(cur_coords["longitude"]), 5)

            matching_locations = []
            for h in same_collector_history:
                h_coords = h.collection_coordinates
                if h_coords and "latitude" in h_coords and "longitude" in h_coords:
                    if (
                        round(float(h_coords["latitude"]), 5) == cur_lat
                        and round(float(h_coords["longitude"]), 5) == cur_lon
                    ):
                        matching_locations.append(h)

            if len(matching_locations) >= 4:
                flags.append(
                    SentinelFlagCreate(
                        detector=self.name,
                        severity=RiskLevel.MEDIUM,
                        reason=(
                            f"Static coordinate clustering: exact geographic point ({cur_lat}, {cur_lon}) "
                            f"reused across {len(matching_locations) + 1} separate collection events."
                        ),
                        confidence=0.75,
                        evidence_reference=str(recovery.id),
                        metadata={
                            "latitude": cur_lat,
                            "longitude": cur_lon,
                            "cluster_size": len(matching_locations) + 1,
                        },
                    )
                )

        # 3. Burst Velocity / Rapid Multi-Submission
        # Physical field collection takes time. 4+ recoveries submitted in under 10 minutes indicates scripting or bulk entry.
        cur_created_at = recovery.created_at
        if cur_created_at.tzinfo is None:
            cur_created_at = cur_created_at.replace(tzinfo=timezone.utc)

        burst_events = []
        for h in same_collector_history:
            h_created_at = h.created_at
            if h_created_at.tzinfo is None:
                h_created_at = h_created_at.replace(tzinfo=timezone.utc)

            delta_seconds = abs((cur_created_at - h_created_at).total_seconds())
            if delta_seconds <= 600:  # Within 10 minutes
                burst_events.append(h)

        if len(burst_events) >= 4:
            flags.append(
                SentinelFlagCreate(
                    detector=self.name,
                    severity=RiskLevel.HIGH,
                    reason=(
                        f"High-frequency submission burst: collector created {len(burst_events) + 1} recovery events "
                        f"within a 10-minute window."
                    ),
                    confidence=0.85,
                    evidence_reference=str(recovery.id),
                    metadata={
                        "burst_count": len(burst_events) + 1,
                        "window_seconds": 600,
                    },
                )
            )

        return flags
