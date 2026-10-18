"""PLASTIFY SENTINEL Machine Learning Model Abstraction."""

from abc import ABC, abstractmethod
import logging
from typing import Any, Dict

logger = logging.getLogger("plastify.sentinel.ml")


class BaseAnomalyModelService(ABC):
    """Abstract interface for statistical and predictive machine learning models."""

    @abstractmethod
    def predict_risk(self, feature_vector: Dict[str, Any]) -> Dict[str, Any]:
        """Generate risk probability and classification from extracted features."""
        pass

    @abstractmethod
    def extract_feature_vector(self, recovery_payload: Dict[str, Any]) -> Dict[str, float]:
        """Transform domain recovery attributes into standardized numerical feature representations."""
        pass


class HeuristicAnomalyModelService(BaseAnomalyModelService):
    """Rule-based heuristic ML model adapter for MVP.

    Computes normalized multi-factor anomaly scores, providing a drop-in foundation
    for XGBoost, Isolation Forest, or PyTorch neural networks.
    """

    def extract_feature_vector(self, recovery_payload: Dict[str, Any]) -> Dict[str, float]:
        """Convert input parameters into standard 0.0-1.0 normalized features."""
        weight_kg = float(recovery_payload.get("weight_kg", 0.0))
        discrepancy_pct = float(recovery_payload.get("discrepancy_pct", 0.0))
        evidence_count = float(recovery_payload.get("evidence_count", 0.0))

        # Normalized feature representations
        return {
            "norm_weight": min(weight_kg / 1000.0, 1.0),
            "norm_discrepancy": min(abs(discrepancy_pct) / 100.0, 1.0),
            "norm_evidence_completeness": min(evidence_count / 3.0, 1.0),
            "geo_validity": 1.0 if recovery_payload.get("has_valid_coords") else 0.0,
        }

    def predict_risk(self, feature_vector: Dict[str, Any]) -> Dict[str, Any]:
        """Compute synthetic anomaly score and confidence interval."""
        norm_disc = feature_vector.get("norm_discrepancy", 0.0)
        norm_ev = feature_vector.get("norm_evidence_completeness", 1.0)
        geo_valid = feature_vector.get("geo_validity", 1.0)

        # Heuristic risk weight calculation
        raw_risk = (norm_disc * 0.50) + ((1.0 - norm_ev) * 0.25) + ((1.0 - geo_valid) * 0.25)
        risk_score = round(min(max(raw_risk * 100.0, 0.0), 100.0), 2)

        return {
            "model_version": "heuristic-v1.0",
            "predicted_risk_score": risk_score,
            "feature_contributions": {
                "weight_discrepancy": norm_disc * 0.50,
                "missing_evidence": (1.0 - norm_ev) * 0.25,
                "invalid_geography": (1.0 - geo_valid) * 0.25,
            },
            "model_confidence": 0.85,
        }
