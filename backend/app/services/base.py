"""PLASTIFY Base Service Layer.

Base class providing shared service capabilities and dependency injection support.
"""

import logging


class BaseService:
    """Base class for domain and infrastructure services."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"plastify.{self.__class__.__name__}")
