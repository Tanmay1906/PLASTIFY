"""PLASTIFY Base External Integration Client.

Provides resilient HTTP client capabilities with timeouts, headers,
and error normalization for third-party service adapters.
"""

import logging
from typing import Any, Dict, Optional
import httpx

from app.core.exceptions import ServiceUnavailableException
from app.core.logging import get_current_request_id


class BaseExternalClient:
    """Base HTTP client for external integrations."""

    def __init__(
        self,
        base_url: str,
        service_name: str,
        timeout: float = 10.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_name = service_name
        self.timeout = timeout
        self.default_headers = headers or {}
        self.logger = logging.getLogger(f"plastify.integrations.{service_name}")
        self._client: Optional[httpx.AsyncClient] = None

    async def get_client(self) -> httpx.AsyncClient:
        """Initialize or retrieve the underlying httpx AsyncClient."""
        if self._client is None or self._client.is_closed:
            headers = {
                "User-Agent": "Plastify-Backend/1.0",
                **self.default_headers,
            }
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=headers,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client connection pool."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """Execute HTTP request with correlation tracking and error handling."""
        client = await self.get_client()
        headers = dict(extra_headers or {})

        request_id = get_current_request_id()
        if request_id:
            headers["X-Request-ID"] = request_id

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        self.logger.debug(f"External call to {self.service_name}: {method} {url}")

        try:
            response = await client.request(
                method=method,
                url=endpoint,
                params=params,
                json=json_data,
                headers=headers,
            )
            return response
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            self.logger.error(
                f"Connection failure communicating with {self.service_name}: {exc}",
                extra={"service": self.service_name, "error": str(exc)},
            )
            raise ServiceUnavailableException(
                message=f"External service '{self.service_name}' is unreachable.",
                details={"service": self.service_name, "error": str(exc)},
            ) from exc
