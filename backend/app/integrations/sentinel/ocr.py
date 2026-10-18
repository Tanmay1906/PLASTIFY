"""PLASTIFY SENTINEL Optical Character Recognition (OCR) Abstraction."""

from abc import ABC, abstractmethod
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("plastify.sentinel.ocr")


class BaseOCRService(ABC):
    """Abstract interface for document and scale digit optical character recognition."""

    @abstractmethod
    async def extract_text(self, image_bytes: bytes, filename: Optional[str] = None) -> str:
        """Extract raw text transcription from image binary data."""
        pass

    @abstractmethod
    async def extract_weight_reading(
        self, image_bytes: bytes, filename: Optional[str] = None
    ) -> Optional[float]:
        """Parse numeric weight value from tare scale display or printed weighbridge ticket."""
        pass

    @abstractmethod
    async def extract_receipt_metadata(
        self, image_bytes: bytes, filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Extract structured entities (dates, gross/tare/net weights, ticket serial numbers)."""
        pass


class RuleBasedOCRService(BaseOCRService):
    """Deterministic / regex-based OCR parser for MVP and test automation.

    Provides a clean pluggable foundation that can be swapped with Tesseract, AWS Textract,
    or Google Cloud Vision in production.
    """

    # Matches weight indicators like "Net: 99.5 kg", "100.25 KG", "Gross 105.00kg"
    WEIGHT_REGEX = re.compile(
        r"(?:weight|net|tare|gross|mass)?[:\s]*([0-9]+(?:\.[0-9]+)?)\s*(?:kg|kgs|kilograms)",
        re.IGNORECASE,
    )
    DATE_REGEX = re.compile(
        r"(\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})"
    )

    async def extract_text(self, image_bytes: bytes, filename: Optional[str] = None) -> str:
        """Perform text extraction (extracts readable strings from binary or simulated tokens)."""
        if not image_bytes:
            return ""
        try:
            # Extract printable ASCII/UTF-8 strings from binary stream
            text_fragment = image_bytes.decode("utf-8", errors="ignore")
            # Filter sequences of 4 or more printable alphanumeric characters
            words = re.findall(r"[A-Za-z0-9.:\-_/]{4,}", text_fragment)
            return " ".join(words)
        except Exception as exc:
            logger.debug(f"RuleBasedOCR text extraction fallback: {exc}")
            return ""

    async def extract_weight_reading(
        self, image_bytes: bytes, filename: Optional[str] = None
    ) -> Optional[float]:
        """Detect numeric weight values inside text or filename patterns."""
        # 1. Check filename hint (e.g. scale_100_5kg.jpg)
        if filename:
            fn_match = self.WEIGHT_REGEX.search(filename)
            if fn_match:
                try:
                    return float(fn_match.group(1))
                except ValueError:
                    pass

        # 2. Check binary string content
        text = await self.extract_text(image_bytes, filename)
        match = self.WEIGHT_REGEX.search(text)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

        return None

    async def extract_receipt_metadata(
        self, image_bytes: bytes, filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """Extract structured receipt metadata."""
        text = await self.extract_text(image_bytes, filename)
        weight = await self.extract_weight_reading(image_bytes, filename)
        date_match = self.DATE_REGEX.search(text)

        return {
            "parsed_weight_kg": weight,
            "detected_date": date_match.group(1) if date_match else None,
            "has_scale_digits": weight is not None,
            "raw_text_length": len(text),
        }
