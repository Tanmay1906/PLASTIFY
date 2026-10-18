"""PLASTIFY SENTINEL Delivery Mismatch Detector."""

import logging
from typing import List

from app.models.logistics import DeliveryStatus
from app.models.sentinel import RiskLevel
from app.schemas.sentinel import SentinelFlagCreate
from app.services.sentinel.base import BaseSentinelDetector
from app.services.sentinel.context import SentinelContext

logger = logging.getLogger("plastify.sentinel.detectors.delivery_mismatch")


class DeliveryMismatchDetector(BaseSentinelDetector):
    """Reconciles physical plastic quantities and states across logistics chain milestones."""

    @property
    def name(self) -> str:
        return "DeliveryMismatchDetector"

    @property
    def description(self) -> str:
        return "Compares collection weight, carrier handoff weight, and recycler received weight."

    async def evaluate(self, context: SentinelContext) -> List[SentinelFlagCreate]:
        flags: List[SentinelFlagCreate] = []
        recovery = context.recovery
        assignment = context.assignment
        delivery = context.delivery

        # 1. Check if Delivery Record is Missing for an advanced custody event
        if recovery.custody_status in ["DELIVERED", "RECEIVED", "VERIFIED"] and not delivery:
            flags.append(
                SentinelFlagCreate(
                    detector=self.name,
                    severity=RiskLevel.HIGH,
                    reason=(
                        f"Custody paradox: recovery event custody status is '{recovery.custody_status}' "
                        f"but no corresponding logistics delivery record exists in the system."
                    ),
                    confidence=0.95,
                    evidence_reference=str(recovery.id),
                    metadata={"custody_status": recovery.custody_status},
                )
            )
            return flags

        if not delivery:
            return flags

        # 2. Reconcile Declared Collection vs Logistics Expected Weight
        if delivery.expected_weight_kg and recovery.weight_kg:
            weight_diff = abs(delivery.expected_weight_kg - recovery.weight_kg)
            if weight_diff > 0.01:
                diff_pct = (weight_diff / recovery.weight_kg) * 100.0
                if diff_pct > 5.0:
                    flags.append(
                        SentinelFlagCreate(
                            detector=self.name,
                            severity=RiskLevel.MEDIUM if diff_pct <= 15.0 else RiskLevel.HIGH,
                            reason=(
                                f"Pickup quantity mismatch: collection record specifies {recovery.weight_kg:.2f} kg "
                                f"but transport consignment manifest specifies {delivery.expected_weight_kg:.2f} kg "
                                f"({diff_pct:.1f}% divergence)."
                            ),
                            confidence=0.90,
                            evidence_reference=str(delivery.id),
                            metadata={
                                "collection_weight_kg": recovery.weight_kg,
                                "expected_weight_kg": delivery.expected_weight_kg,
                                "difference_kg": round(weight_diff, 2),
                                "difference_pct": round(diff_pct, 2),
                            },
                        )
                    )

        # 3. Carrier Delivered vs Recycler Received Discrepancy
        if delivery.delivered_weight_kg is not None and delivery.received_weight_kg is not None:
            carrier_wt = delivery.delivered_weight_kg
            recycler_wt = delivery.received_weight_kg
            handoff_diff = abs(carrier_wt - recycler_wt)
            handoff_pct = (handoff_diff / carrier_wt * 100.0) if carrier_wt > 0 else 0.0

            # Normal scale tolerance of 2.0%
            if handoff_pct > 2.0:
                flags.append(
                    SentinelFlagCreate(
                        detector=self.name,
                        severity=RiskLevel.HIGH if handoff_pct > 10.0 else RiskLevel.MEDIUM,
                        reason=(
                            f"Handoff discrepancy at recycler intake: carrier delivered {carrier_wt:.2f} kg "
                            f"but recycler weighed in {recycler_wt:.2f} kg ({handoff_pct:.1f}% variation)."
                        ),
                        confidence=0.88,
                        evidence_reference=str(delivery.id),
                        metadata={
                            "delivered_weight_kg": carrier_wt,
                            "received_weight_kg": recycler_wt,
                            "handoff_difference_kg": round(handoff_diff, 2),
                            "handoff_pct": round(handoff_pct, 2),
                        },
                    )
                )

        # 4. Status Alignment Sanity Checks
        if delivery.status == DeliveryStatus.RECEIVED and not delivery.receiver_id:
            flags.append(
                SentinelFlagCreate(
                    detector=self.name,
                    severity=RiskLevel.MEDIUM,
                    reason="Delivery marked RECEIVED without authorized receiving officer identity.",
                    confidence=0.85,
                    evidence_reference=str(delivery.id),
                    metadata={"delivery_status": delivery.status.value},
                )
            )

        return flags
