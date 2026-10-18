"""PLASTIFY SENTINEL Weight Anomaly Detector."""

import logging
from typing import List

from app.models.sentinel import RiskLevel
from app.schemas.sentinel import SentinelFlagCreate
from app.services.sentinel.base import BaseSentinelDetector
from app.services.sentinel.context import SentinelContext

logger = logging.getLogger("plastify.sentinel.detectors.weight")


class WeightAnomalyDetector(BaseSentinelDetector):
    """Detects irregular weight readings, transit discrepancies, and statistical collection spikes."""

    @property
    def name(self) -> str:
        return "WeightAnomalyDetector"

    @property
    def description(self) -> str:
        return "Analyzes collected vs delivered weights, transit gain/loss, and historical statistical ranges."

    async def evaluate(self, context: SentinelContext) -> List[SentinelFlagCreate]:
        flags: List[SentinelFlagCreate] = []
        recovery = context.recovery
        delivery = context.delivery

        # Configurable tolerances (defaults: warning at 5%, severe at 15%, critical at 30%)
        tolerance_pct = float(
            context.config.get("weight_tolerance_pct", delivery.weight_tolerance_pct if delivery else 5.0)
        )
        extreme_spike_threshold_kg = float(context.config.get("max_single_collection_kg", 5000.0))

        # 1. Absolute Weight Sanity Checks
        if recovery.weight_kg <= 0:
            flags.append(
                SentinelFlagCreate(
                    detector=self.name,
                    severity=RiskLevel.CRITICAL,
                    reason=f"Impossible non-positive collection weight recorded: {recovery.weight_kg} kg.",
                    confidence=1.0,
                    evidence_reference=str(recovery.id),
                    metadata={"weight_kg": recovery.weight_kg},
                )
            )
        elif recovery.weight_kg > extreme_spike_threshold_kg:
            flags.append(
                SentinelFlagCreate(
                    detector=self.name,
                    severity=RiskLevel.HIGH,
                    reason=(
                        f"Unusually large single collection batch of {recovery.weight_kg} kg "
                        f"exceeds standard threshold of {extreme_spike_threshold_kg} kg."
                    ),
                    confidence=0.85,
                    evidence_reference=str(recovery.id),
                    metadata={
                        "weight_kg": recovery.weight_kg,
                        "threshold_kg": extreme_spike_threshold_kg,
                    },
                )
            )

        # 2. Historical Baseline Comparison (Collector Spikes)
        if context.historical_recoveries and recovery.weight_kg > 0:
            past_weights = [r.weight_kg for r in context.historical_recoveries if r.weight_kg > 0 and r.id != recovery.id]
            if len(past_weights) >= 3:
                avg_past_weight = sum(past_weights) / len(past_weights)
                # If current recovery is more than 5x the collector's historical average
                if recovery.weight_kg > (avg_past_weight * 5.0) and recovery.weight_kg > 500.0:
                    flags.append(
                        SentinelFlagCreate(
                            detector=self.name,
                            severity=RiskLevel.MEDIUM,
                            reason=(
                                f"Batch weight of {recovery.weight_kg} kg represents a statistical outlier "
                                f"relative to collector historical average of {avg_past_weight:.1f} kg."
                            ),
                            confidence=0.75,
                            evidence_reference=str(recovery.id),
                            metadata={
                                "weight_kg": recovery.weight_kg,
                                "historical_average_kg": round(avg_past_weight, 2),
                                "sample_size": len(past_weights),
                            },
                        )
                    )

        # 3. Collection vs Delivered / Received Weight Discrepancy
        if delivery and delivery.received_weight_kg is not None:
            expected_wt = delivery.expected_weight_kg or recovery.weight_kg
            received_wt = delivery.received_weight_kg
            discrepancy_kg = abs(expected_wt - received_wt)
            discrepancy_pct = (discrepancy_kg / expected_wt * 100.0) if expected_wt > 0 else 0.0

            # Only flag if discrepancy strictly exceeds configured tolerance
            if discrepancy_pct > tolerance_pct:
                if discrepancy_pct > 30.0:
                    severity = RiskLevel.CRITICAL
                    reason = (
                        f"Critical weight divergence: expected {expected_wt:.2f} kg vs received "
                        f"{received_wt:.2f} kg ({discrepancy_pct:.1f}% discrepancy exceeds {tolerance_pct}% tolerance)."
                    )
                elif discrepancy_pct > 15.0:
                    severity = RiskLevel.HIGH
                    reason = (
                        f"High weight discrepancy: expected {expected_wt:.2f} kg vs received "
                        f"{received_wt:.2f} kg ({discrepancy_pct:.1f}% discrepancy exceeds {tolerance_pct}% tolerance)."
                    )
                else:
                    severity = RiskLevel.MEDIUM
                    reason = (
                        f"Moderate weight discrepancy: expected {expected_wt:.2f} kg vs received "
                        f"{received_wt:.2f} kg ({discrepancy_pct:.1f}% discrepancy exceeds {tolerance_pct}% tolerance)."
                    )

                flags.append(
                    SentinelFlagCreate(
                        detector=self.name,
                        severity=severity,
                        reason=reason,
                        confidence=0.95,
                        evidence_reference=str(delivery.id),
                        metadata={
                            "expected_weight_kg": expected_wt,
                            "received_weight_kg": received_wt,
                            "discrepancy_kg": round(discrepancy_kg, 2),
                            "discrepancy_pct": round(discrepancy_pct, 2),
                            "tolerance_pct": tolerance_pct,
                        },
                    )
                )

            # Check for physically suspicious weight inflation along transit
            if received_wt > (expected_wt * 1.05):  # Gained more than 5% during transit
                gain_kg = received_wt - expected_wt
                gain_pct = (gain_kg / expected_wt) * 100.0
                flags.append(
                    SentinelFlagCreate(
                        detector=self.name,
                        severity=RiskLevel.HIGH,
                        reason=(
                            f"Suspicious physical mass inflation in transit: batch weight expanded from "
                            f"{expected_wt:.2f} kg to {received_wt:.2f} kg (+{gain_pct:.1f}% gain)."
                        ),
                        confidence=0.88,
                        evidence_reference=str(delivery.id),
                        metadata={
                            "expected_weight_kg": expected_wt,
                            "received_weight_kg": received_wt,
                            "gain_kg": round(gain_kg, 2),
                            "gain_pct": round(gain_pct, 2),
                        },
                    )
                )

        return flags
