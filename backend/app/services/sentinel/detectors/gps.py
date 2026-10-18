"""PLASTIFY SENTINEL GPS & Geofence Anomaly Detector."""

import logging
import math
from typing import Dict, List, Optional, Tuple

from app.models.sentinel import RiskLevel
from app.schemas.sentinel import SentinelFlagCreate
from app.services.sentinel.base import BaseSentinelDetector
from app.services.sentinel.context import SentinelContext

logger = logging.getLogger("plastify.sentinel.detectors.gps")

# Well-known regional bounding boxes for regional sanity checks: (min_lat, max_lat, min_lon, max_lon)
KNOWN_REGION_BOUNDS: Dict[str, Tuple[float, float, float, float]] = {
    "mumbai": (18.5, 19.8, 72.5, 73.5),
    "maharashtra": (15.5, 22.5, 72.0, 81.0),
    "delhi": (28.2, 29.0, 76.8, 77.6),
    "goa": (14.8, 15.9, 73.5, 74.5),
    "kerala": (8.0, 13.0, 74.8, 77.6),
    "bali": (-9.1, -8.0, 114.4, 115.8),
    "jakarta": (-6.5, -6.0, 106.6, 107.0),
    "indonesia": (-11.0, 6.0, 95.0, 141.0),
    "vietnam": (8.0, 24.0, 102.0, 110.0),
    "philippines": (4.5, 21.5, 116.5, 127.0),
}


class GPSAnomalyDetector(BaseSentinelDetector):
    """Detects invalid geographic coordinates, geofence breaches, and impossible collector velocities."""

    @property
    def name(self) -> str:
        return "GPSAnomalyDetector"

    @property
    def description(self) -> str:
        return "Validates collection GPS coordinates against program geofences and historical spatial velocity."

    def _haversine_km(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate great circle distance between two points in kilometers."""
        earth_radius_km = 6371.0
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = (
            math.sin(d_lat / 2.0) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(d_lon / 2.0) ** 2
        )
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return earth_radius_km * c

    async def evaluate(self, context: SentinelContext) -> List[SentinelFlagCreate]:
        flags: List[SentinelFlagCreate] = []
        recovery = context.recovery
        coords = recovery.collection_coordinates

        # 1. Missing or Null Coordinates
        if not coords:
            flags.append(
                SentinelFlagCreate(
                    detector=self.name,
                    severity=RiskLevel.LOW,
                    reason="Collection event logged without precise GPS coordinate metadata.",
                    confidence=0.70,
                    evidence_reference=str(recovery.id),
                    metadata={"has_coordinates": False},
                )
            )
            return flags

        lat = coords.get("latitude")
        lon = coords.get("longitude")

        # 2. Mathematical Validity Checks
        if lat is None or lon is None:
            flags.append(
                SentinelFlagCreate(
                    detector=self.name,
                    severity=RiskLevel.MEDIUM,
                    reason="Incomplete GPS coordinate structure (missing latitude or longitude component).",
                    confidence=0.90,
                    evidence_reference=str(recovery.id),
                    metadata={"coordinates": coords},
                )
            )
            return flags

        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            flags.append(
                SentinelFlagCreate(
                    detector=self.name,
                    severity=RiskLevel.CRITICAL,
                    reason=f"Impossible out-of-range GPS coordinates: lat={lat}, lon={lon}.",
                    confidence=1.0,
                    evidence_reference=str(recovery.id),
                    metadata={"latitude": lat, "longitude": lon},
                )
            )
            return flags

        # Check for Null Island (0.0, 0.0) coordinates
        if abs(lat) < 0.0001 and abs(lon) < 0.0001:
            flags.append(
                SentinelFlagCreate(
                    detector=self.name,
                    severity=RiskLevel.HIGH,
                    reason="Collection coordinates pinpointed at default Null Island (0.0, 0.0) off Gulf of Guinea.",
                    confidence=0.95,
                    evidence_reference=str(recovery.id),
                    metadata={"latitude": lat, "longitude": lon},
                )
            )

        # 3. Program Region / Geofence Verification
        if context.program and context.program.region:
            prog_region = context.program.region.lower().strip()
            # Match against known bounding boxes
            for reg_key, (min_lat, max_lat, min_lon, max_lon) in KNOWN_REGION_BOUNDS.items():
                if reg_key in prog_region:
                    if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
                        flags.append(
                            SentinelFlagCreate(
                                detector=self.name,
                                severity=RiskLevel.HIGH,
                                reason=(
                                    f"Collection coordinates ({lat:.4f}, {lon:.4f}) fall outside program's "
                                    f"designated '{context.program.region}' operational zone."
                                ),
                                confidence=0.90,
                                evidence_reference=str(recovery.id),
                                metadata={
                                    "latitude": lat,
                                    "longitude": lon,
                                    "program_region": context.program.region,
                                    "expected_bounds": {
                                        "min_lat": min_lat,
                                        "max_lat": max_lat,
                                        "min_lon": min_lon,
                                        "max_lon": max_lon,
                                    },
                                },
                            )
                        )
                    break

        # 4. Impossible Travel Velocity (Teleportation Check)
        if context.historical_recoveries:
            for hist in context.historical_recoveries:
                if hist.id == recovery.id or not hist.collection_coordinates:
                    continue

                h_lat = hist.collection_coordinates.get("latitude")
                h_lon = hist.collection_coordinates.get("longitude")
                if h_lat is None or h_lon is None:
                    continue

                # Calculate elapsed time in hours
                time_diff = abs((recovery.collected_at - hist.collected_at).total_seconds())
                if time_diff == 0:
                    continue
                time_diff_hours = time_diff / 3600.0

                # Only check reasonably recent events (< 24 hours apart)
                if time_diff_hours <= 12.0:
                    distance_km = self._haversine_km(lat, lon, h_lat, h_lon)
                    implied_speed_kmh = distance_km / time_diff_hours

                    # Flag speed exceeding 200 km/h as impossible ground mobility
                    if implied_speed_kmh > 200.0 and distance_km > 50.0:
                        flags.append(
                            SentinelFlagCreate(
                                detector=self.name,
                                severity=RiskLevel.CRITICAL if implied_speed_kmh > 500.0 else RiskLevel.HIGH,
                                reason=(
                                    f"Impossible spatial velocity: collector recorded events {distance_km:.1f} km "
                                    f"apart within {time_diff / 60.0:.1f} minutes ({implied_speed_kmh:.0f} km/h)."
                                ),
                                confidence=0.92,
                                evidence_reference=str(hist.id),
                                metadata={
                                    "distance_km": round(distance_km, 2),
                                    "elapsed_minutes": round(time_diff / 60.0, 1),
                                    "implied_speed_kmh": round(implied_speed_kmh, 1),
                                    "prior_recovery_id": str(hist.id),
                                },
                            )
                        )
                        break

        return flags
