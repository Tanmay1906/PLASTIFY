"""PLASTIFY SENTINEL Timestamp & Chronology Anomaly Detector."""

from datetime import datetime, timezone
import logging
from typing import List

from app.models.sentinel import RiskLevel
from app.schemas.sentinel import SentinelFlagCreate
from app.services.sentinel.base import BaseSentinelDetector
from app.services.sentinel.context import SentinelContext

logger = logging.getLogger("plastify.sentinel.detectors.timestamp")


class TimestampAnomalyDetector(BaseSentinelDetector):
    """Detects chronology paradoxes, inverted operational milestones, and impossible future timestamps."""

    @property
    def name(self) -> str:
        return "TimestampAnomalyDetector"

    @property
    def description(self) -> str:
        return "Enforces chronological milestones across collection, pickup, transport, delivery, and receipt."

    async def evaluate(self, context: SentinelContext) -> List[SentinelFlagCreate]:
        flags: List[SentinelFlagCreate] = []
        recovery = context.recovery
        delivery = context.delivery
        now = datetime.now(timezone.utc)

        # 1. Future Timestamp Sanity Check (5 minutes grace for clock drift)
        collected_at = recovery.collected_at
        if collected_at.tzinfo is None:
            collected_at = collected_at.replace(tzinfo=timezone.utc)

        if (collected_at - now).total_seconds() > 300:
            flags.append(
                SentinelFlagCreate(
                    detector=self.name,
                    severity=RiskLevel.CRITICAL,
                    reason=(
                        f"Post-dated collection: event timestamp {collected_at.isoformat()} "
                        f"lies in the future relative to server time {now.isoformat()}."
                    ),
                    confidence=1.0,
                    evidence_reference=str(recovery.id),
                    metadata={
                        "collected_at": collected_at.isoformat(),
                        "server_now": now.isoformat(),
                    },
                )
            )

        # 2. Extreme Latency / Stale Collection (e.g. > 180 days)
        if (now - collected_at).days > 180:
            flags.append(
                SentinelFlagCreate(
                    detector=self.name,
                    severity=RiskLevel.MEDIUM,
                    reason=(
                        f"Stale collection record: physical collection date {collected_at.strftime('%Y-%m-%d')} "
                        f"is over 180 days older than current audit cycle."
                    ),
                    confidence=0.80,
                    evidence_reference=str(recovery.id),
                    metadata={"days_elapsed": (now - collected_at).days},
                )
            )

        # 3. Delivery Milestones Chronology Invariants
        if delivery:
            pickup_ts = delivery.pickup_timestamp
            if pickup_ts and pickup_ts.tzinfo is None:
                pickup_ts = pickup_ts.replace(tzinfo=timezone.utc)

            intransit_ts = delivery.in_transit_timestamp
            if intransit_ts and intransit_ts.tzinfo is None:
                intransit_ts = intransit_ts.replace(tzinfo=timezone.utc)

            delivery_ts = delivery.delivery_timestamp
            if delivery_ts and delivery_ts.tzinfo is None:
                delivery_ts = delivery_ts.replace(tzinfo=timezone.utc)

            received_ts = delivery.received_timestamp
            if received_ts and received_ts.tzinfo is None:
                received_ts = received_ts.replace(tzinfo=timezone.utc)

            # Pickup occurred before physical collection was logged
            if pickup_ts and pickup_ts < collected_at:
                flags.append(
                    SentinelFlagCreate(
                        detector=self.name,
                        severity=RiskLevel.HIGH,
                        reason=(
                            f"Inverted milestone: carrier pickup timestamp ({pickup_ts.isoformat()}) "
                            f"precedes recorded plastic collection timestamp ({collected_at.isoformat()})."
                        ),
                        confidence=0.95,
                        evidence_reference=str(delivery.id),
                        metadata={
                            "pickup_timestamp": pickup_ts.isoformat(),
                            "collected_at": collected_at.isoformat(),
                        },
                    )
                )

            # In-transit timestamp precedes pickup
            if intransit_ts and pickup_ts and intransit_ts < pickup_ts:
                flags.append(
                    SentinelFlagCreate(
                        detector=self.name,
                        severity=RiskLevel.HIGH,
                        reason=(
                            f"Inverted logistics milestone: consignment departure ({intransit_ts.isoformat()}) "
                            f"precedes carrier pickup confirmation ({pickup_ts.isoformat()})."
                        ),
                        confidence=0.90,
                        evidence_reference=str(delivery.id),
                        metadata={
                            "in_transit_timestamp": intransit_ts.isoformat(),
                            "pickup_timestamp": pickup_ts.isoformat(),
                        },
                    )
                )

            # Delivered occurred before pickup
            if delivery_ts and pickup_ts and delivery_ts < pickup_ts:
                flags.append(
                    SentinelFlagCreate(
                        detector=self.name,
                        severity=RiskLevel.CRITICAL,
                        reason=(
                            f"Impossible chronology: destination drop-off ({delivery_ts.isoformat()}) "
                            f"is recorded prior to pickup ({pickup_ts.isoformat()})."
                        ),
                        confidence=1.0,
                        evidence_reference=str(delivery.id),
                        metadata={
                            "delivery_timestamp": delivery_ts.isoformat(),
                            "pickup_timestamp": pickup_ts.isoformat(),
                        },
                    )
                )

            # Recycler confirmed receipt prior to logistics delivery
            if received_ts and delivery_ts and received_ts < delivery_ts:
                flags.append(
                    SentinelFlagCreate(
                        detector=self.name,
                        severity=RiskLevel.HIGH,
                        reason=(
                            f"Inverted delivery milestone: recycler confirmation ({received_ts.isoformat()}) "
                            f"is stamped earlier than carrier drop-off ({delivery_ts.isoformat()})."
                        ),
                        confidence=0.92,
                        evidence_reference=str(delivery.id),
                        metadata={
                            "received_timestamp": received_ts.isoformat(),
                            "delivery_timestamp": delivery_ts.isoformat(),
                        },
                    )
                )

            # Suspicious instantaneous transit duration (< 1 minute)
            if delivery_ts and pickup_ts and delivery_ts >= pickup_ts:
                transit_seconds = (delivery_ts - pickup_ts).total_seconds()
                if transit_seconds < 60:
                    flags.append(
                        SentinelFlagCreate(
                            detector=self.name,
                            severity=RiskLevel.MEDIUM,
                            reason=(
                                f"Suspiciously rapid logistics cycle: elapsed time between pickup and delivery "
                                f"was only {transit_seconds:.0f} seconds."
                            ),
                            confidence=0.75,
                            evidence_reference=str(delivery.id),
                            metadata={"transit_seconds": transit_seconds},
                        )
                    )

        return flags
