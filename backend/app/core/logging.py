"""PLASTIFY Structured Logging Module.

Provides JSON and console formatters with correlation ID context tracking.
Ensures zero external C-dependencies for maximum reliability and portability.
"""

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Context variable for correlation/request ID propagation across async tasks
request_id_ctx_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)


def get_current_request_id() -> Optional[str]:
    """Retrieve the current request ID from contextvars."""
    return request_id_ctx_var.get()


def set_current_request_id(request_id: Optional[str]) -> None:
    """Set the current request ID in contextvars."""
    request_id_ctx_var.set(request_id)


class JSONFormatter(logging.Formatter):
    """Custom logging formatter that produces structured JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Include request ID if present in context or record
        request_id = getattr(record, "request_id", None) or get_current_request_id()
        if request_id:
            log_data["request_id"] = request_id

        # Include exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Include any extra attributes passed via extra={}
        extra_attrs = {
            k: v
            for k, v in record.__dict__.items()
            if k not in {
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "id",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
                "request_id",
            }
        }
        if extra_attrs:
            log_data["extra"] = extra_attrs

        return json.dumps(log_data, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-friendly console log formatter with color codes and request ID."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[41m",  # Red background
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        request_id = getattr(record, "request_id", None) or get_current_request_id()
        req_str = f" [{request_id}]" if request_id else ""
        time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        msg = f"{color}[{time_str}] [{record.levelname:<8}]{self.RESET}{req_str} {record.name}: {record.getMessage()}"

        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)

        return msg


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> logging.Logger:
    """Configure the root logger and third-party loggers."""
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())

    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if log_format.lower() == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(ConsoleFormatter())

    root_logger.addHandler(handler)

    # Quiet overly chatty loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    logger = logging.getLogger("plastify")
    logger.info("Logging configured", extra={"log_level": log_level, "log_format": log_format})
    return logger
