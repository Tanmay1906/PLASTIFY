"""PLASTIFY Core Exception Hierarchy.

Defines standard domain and infrastructure exceptions with error codes
and status codes to decouple HTTP handling from business logic.
"""

from typing import Any, Dict, Optional


class PlastifyException(Exception):
    """Base exception for all application-specific errors."""

    status_code: int = 500
    error_code: str = "INTERNAL_SERVER_ERROR"
    message: str = "An unexpected internal error occurred."

    def __init__(
        self,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        if message:
            self.message = message
        if error_code:
            self.error_code = error_code
        if status_code:
            self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class BadRequestException(PlastifyException):
    """Exception raised when an invalid request is supplied."""

    status_code = 400
    error_code = "BAD_REQUEST"
    message = "Bad request parameters."


class UnauthorizedException(PlastifyException):
    """Exception raised when authentication credentials are missing or invalid."""

    status_code = 401
    error_code = "UNAUTHORIZED"
    message = "Authentication required."


class ForbiddenException(PlastifyException):
    """Exception raised when authorization to perform an action is denied."""

    status_code = 403
    error_code = "FORBIDDEN"
    message = "Access forbidden."


class NotFoundException(PlastifyException):
    """Exception raised when a requested resource is not found."""

    status_code = 404
    error_code = "RESOURCE_NOT_FOUND"
    message = "Requested resource was not found."


class ConflictException(PlastifyException):
    """Exception raised when a state conflict occurs (e.g. duplicate resource)."""

    status_code = 409
    error_code = "RESOURCE_CONFLICT"
    message = "Resource conflict detected."


class ValidationException(PlastifyException):
    """Exception raised when domain validation rules are violated."""

    status_code = 422
    error_code = "VALIDATION_FAILED"
    message = "Validation check failed."


class ServiceUnavailableException(PlastifyException):
    """Exception raised when an external or infrastructure dependency is down."""

    status_code = 503
    error_code = "SERVICE_UNAVAILABLE"
    message = "Service temporarily unavailable."


class DatabaseConnectionError(ServiceUnavailableException):
    """Exception raised when database connection fails."""

    error_code = "DATABASE_UNAVAILABLE"
    message = "Database connection could not be established or timed out."


class RedisConnectionError(ServiceUnavailableException):
    """Exception raised when Redis connection fails."""

    error_code = "REDIS_UNAVAILABLE"
    message = "Redis cache/broker connection could not be established or timed out."
