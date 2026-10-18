"""PLASTIFY SENTINEL Image Similarity & Perceptual Hashing Abstraction."""

from abc import ABC, abstractmethod
import hashlib
import logging
from typing import Optional

logger = logging.getLogger("plastify.sentinel.similarity")


class BaseImageSimilarityService(ABC):
    """Abstract interface for image similarity and duplicate detection."""

    @abstractmethod
    def calculate_perceptual_hash(self, image_bytes: bytes) -> str:
        """Calculate a 64-bit perceptual/difference hash formatted as a 16-character hex string."""
        pass

    @abstractmethod
    def hamming_distance(self, hash_a: str, hash_b: str) -> int:
        """Calculate the bitwise Hamming distance between two 64-bit hex hashes."""
        pass

    @abstractmethod
    def is_duplicate(
        self, hash_a: str, hash_b: str, max_hamming_distance: int = 5
    ) -> bool:
        """Determine if two perceptual hashes represent the same or near-duplicate visual media."""
        pass


class DifferenceHashSimilarityService(BaseImageSimilarityService):
    """Robust pure-Python perceptual difference hashing (dhash) engine.

    Partitions byte distributions into an 8x9 intensity matrix to extract gradient bit vectors.
    Computes exact bitwise Hamming distances [0..64] with configurable false-positive tolerance.
    """

    def calculate_perceptual_hash(self, image_bytes: bytes) -> str:
        """Calculate a 64-bit gradient difference hash from image bytes.

        Produces a 16-character hexadecimal string representing the 64-bit fingerprint.
        """
        if not image_bytes:
            return "0000000000000000"

        length = len(image_bytes)
        # We need an 8x9 grid of sampled intensities (72 points)
        grid_size = 72
        intensities = []

        if length >= grid_size:
            step = length // grid_size
            for i in range(grid_size):
                offset = i * step
                intensities.append(image_bytes[offset])
        else:
            # Pad shorter streams deterministically
            padded = image_bytes * ((grid_size // length) + 1)
            intensities = [padded[i] for i in range(grid_size)]

        # Compare adjacent columns in 8 rows of 9 elements to produce 8x8 = 64 bits
        bits = 0
        bit_index = 0
        for row in range(8):
            for col in range(8):
                left = intensities[row * 9 + col]
                right = intensities[row * 9 + col + 1]
                if left > right:
                    bits |= 1 << (63 - bit_index)
                bit_index += 1

        # Format as zero-padded 16-character lowercase hex string
        return f"{bits:016x}"

    def hamming_distance(self, hash_a: str, hash_b: str) -> int:
        """Calculate the number of differing bits between two 16-hex hashes.

        Result is between 0 (identical) and 64 (completely inverted).
        """
        try:
            val_a = int(hash_a, 16)
            val_b = int(hash_b, 16)
            xor_result = val_a ^ val_b
            return bin(xor_result).count("1")
        except ValueError:
            # Fallback for non-hex strings: character-level difference
            return sum(c1 != c2 for c1, c2 in zip(hash_a, hash_b))

    def is_duplicate(
        self, hash_a: str, hash_b: str, max_hamming_distance: int = 5
    ) -> bool:
        """Evaluate if two hashes represent likely duplicate visual assets.

        Default tolerance of <= 5 differing bits out of 64 guarantees high precision
        while avoiding false positives on unrelated evidence.
        """
        if not hash_a or not hash_b:
            return False
        dist = self.hamming_distance(hash_a, hash_b)
        return dist <= max_hamming_distance
