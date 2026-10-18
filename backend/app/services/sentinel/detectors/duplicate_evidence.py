"""PLASTIFY SENTINEL Duplicate Evidence Detector."""

import logging
from typing import List, Set

from app.models.sentinel import RiskLevel
from app.schemas.sentinel import SentinelFlagCreate
from app.services.sentinel.base import BaseSentinelDetector
from app.services.sentinel.context import SentinelContext

logger = logging.getLogger("plastify.sentinel.detectors.duplicate_evidence")


class DuplicateEvidenceDetector(BaseSentinelDetector):
    """Detects recycled photographic evidence and duplicate media assets across recovery events."""

    @property
    def name(self) -> str:
        return "DuplicateEvidenceDetector"

    @property
    def description(self) -> str:
        return "Calculates cryptographic (SHA-256) and perceptual gradient hashes to detect reused evidence."

    async def evaluate(self, context: SentinelContext) -> List[SentinelFlagCreate]:
        flags: List[SentinelFlagCreate] = []
        recovery = context.recovery
        current_evidence = context.collection_evidence
        cross_evidence = context.cross_recovery_evidence
        similarity_svc = context.similarity_service

        if not current_evidence:
            flags.append(
                SentinelFlagCreate(
                    detector=self.name,
                    severity=RiskLevel.MEDIUM,
                    reason="No visual photographic evidence records attached to this recovery event.",
                    confidence=0.85,
                    evidence_reference=str(recovery.id),
                    metadata={"evidence_count": 0},
                )
            )
            return flags

        # 1. Intra-batch duplicate check (same file uploaded twice for same recovery)
        seen_local_hashes: Set[str] = set()
        for ev in current_evidence:
            if not ev.sha256_hash:
                continue
            if ev.sha256_hash in seen_local_hashes:
                flags.append(
                    SentinelFlagCreate(
                        detector=self.name,
                        severity=RiskLevel.MEDIUM,
                        reason=(
                            f"Redundant evidence: file '{ev.original_filename}' "
                            f"(SHA256: {ev.sha256_hash[:12]}...) was submitted multiple times within the same event."
                        ),
                        confidence=0.98,
                        evidence_reference=str(ev.id),
                        metadata={
                            "evidence_id": str(ev.id),
                            "sha256_hash": ev.sha256_hash,
                            "filename": ev.original_filename,
                        },
                    )
                )
            seen_local_hashes.add(ev.sha256_hash)

        # 2. Cross-Recovery Exact Match (SHA-256 Collision)
        # Check against past evidence from other recovery events
        for cur_ev in current_evidence:
            if not cur_ev.sha256_hash:
                continue

            for past_ev in cross_evidence:
                if past_ev.recovery_id == recovery.id:
                    continue

                if cur_ev.sha256_hash == past_ev.sha256_hash:
                    flags.append(
                        SentinelFlagCreate(
                            detector=self.name,
                            severity=RiskLevel.CRITICAL,
                            reason=(
                                f"Exact evidence collision: file '{cur_ev.original_filename}' shares identical "
                                f"cryptographic SHA-256 ({cur_ev.sha256_hash[:12]}...) with prior recovery event "
                                f"'{past_ev.recovery.recovery_id if past_ev.recovery else str(past_ev.recovery_id)}'."
                            ),
                            confidence=1.0,
                            evidence_reference=str(cur_ev.id),
                            metadata={
                                "current_evidence_id": str(cur_ev.id),
                                "colliding_evidence_id": str(past_ev.id),
                                "colliding_recovery_id": str(past_ev.recovery_id),
                                "sha256_hash": cur_ev.sha256_hash,
                            },
                        )
                    )
                    break

        # 3. Perceptual Image Similarity Check (dHash)
        # Check if perceptual hashes match or have Hamming distance <= max_tolerance
        max_dist = int(context.config.get("max_perceptual_hamming_distance", 5))

        for cur_ev in current_evidence:
            if not cur_ev.sha256_hash:
                continue
            cur_phash = similarity_svc.calculate_perceptual_hash(cur_ev.sha256_hash.encode("utf-8"))

            for past_ev in cross_evidence:
                if past_ev.recovery_id == recovery.id or not past_ev.sha256_hash:
                    continue

                past_phash = similarity_svc.calculate_perceptual_hash(past_ev.sha256_hash.encode("utf-8"))

                dist = similarity_svc.hamming_distance(cur_phash, past_phash)
                # If hashes are near identical (dist <= max_dist) but distinct SHA-256
                if dist <= max_dist and cur_ev.sha256_hash != past_ev.sha256_hash:
                    confidence = round(1.0 - (dist / 64.0), 2)
                    flags.append(
                        SentinelFlagCreate(
                            detector=self.name,
                            severity=RiskLevel.HIGH,
                            reason=(
                                f"High visual similarity detected: evidence '{cur_ev.original_filename}' resembles "
                                f"evidence from prior recovery (perceptual Hamming distance: {dist}/64)."
                            ),
                            confidence=confidence,
                            evidence_reference=str(cur_ev.id),
                            metadata={
                                "current_evidence_id": str(cur_ev.id),
                                "colliding_evidence_id": str(past_ev.id),
                                "colliding_recovery_id": str(past_ev.recovery_id),
                                "hamming_distance": dist,
                                "threshold": max_dist,
                            },
                        )
                    )
                    break

        return flags
