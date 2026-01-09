from __future__ import annotations

import logging
from typing import Optional, Dict, Any

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import Settings, load_settings
from .models import OptionChainSnapshotResponse

logger = logging.getLogger("massive_client")


class MassiveAPIError(Exception):
    """Raised when the Massive API request fails or returns an unexpected payload."""


class MassiveClient:
    """
    Thin wrapper around the Massive REST API.

    Centralizes:
    - Base URL handling (e.g. https://api.massive.com)
    - Auth header (massive_api_key)
    - Retry policy for transient network failures
    - Logging of outbound requests
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._settings = settings or load_settings()
        base_url = self._settings.massive_base_url.rstrip("/")

        # Shared HTTP client with base_url + auth header
        self._client = client or httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {self._settings.massive_api_key}",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    def close(self) -> None:
        """Close the underlying HTTP client."""
        try:
            self._client.close()
        except Exception:
            logger.exception("Error while closing Massive HTTP client")

    # -------------------------------------------------------------------------
    # Low-level HTTP helper
    # -------------------------------------------------------------------------

    @retry(
        reraise=True,
        retry=retry_if_exception_type(httpx.RequestError),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
    )
    def _get(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Perform a GET to the Massive API with retries and logging.

        `path` MUST start with `/v3/…` – we do **not** include `/v1/` in the base URL.
        """
        logger.info("Massive API request | url=%s | params=%s", path, params)

        try:
            resp = self._client.get(path, params=params)
        except httpx.RequestError as exc:
            logger.error("Massive API network error | url=%s | error=%s", path, exc)
            raise

        if resp.status_code == 404:
            logger.warning(
                "Massive API 404 (no data) | url=%s | body=%s",
                resp.request.url,
                resp.text[:500],
            )
            return {}

        if resp.status_code >= 400:
            logger.error(
                "Massive API request failed | url=%s | status=%s | body=%s",
                resp.request.url,
                resp.status_code,
                resp.text[:500],
            )
            raise MassiveAPIError(
                f"Massive API error {resp.status_code} for {resp.request.url}"
            )

        try:
            return resp.json()
        except ValueError as exc:
            logger.error(
                "Massive API returned invalid JSON | url=%s | body=%s | error=%s",
                resp.request.url,
                resp.text[:500],
                exc,
            )
            return None

    # -------------------------------------------------------------------------
    # High-level methods
    # -------------------------------------------------------------------------

    def get_option_chain_snapshot(
        self,
        symbol: str,
        contract_type: Optional[str] = None,
        limit: int = 250,
    ) -> Optional[OptionChainSnapshotResponse]:
        params: dict = {"limit": limit}
        if contract_type:
            params["contract_type"] = contract_type

        try:
            data = self._get(f"/v3/snapshot/options/{symbol}", params=params)
        except (httpx.RequestError, httpx.HTTPStatusError, RetryError) as exc:
            logger.error("Failed Massive GET for %s: %s", symbol, exc)
            raise MassiveAPIError(str(exc)) from exc

        if not isinstance(data, dict):
            logger.error("Unexpected Massive response for %s", symbol)
            raise MassiveAPIError("Unexpected Massive response type")

        logger.debug("Massive raw keys for %s: %s", symbol, list(data.keys()))

        try:
            snapshot = OptionChainSnapshotResponse.parse_obj(data)
        except Exception as exc:
            logger.exception("Failed to parse Massive snapshot | ticker=%s", symbol)
            raise MassiveAPIError(
                f"Failed to parse option chain snapshot for {symbol}: {exc}"
            ) from exc

        contract_count = len(snapshot.results or [])
        logger.info(
            "Massive option chain fetched | ticker=%s | contracts=%s",
            symbol,
            contract_count,
        )

        return snapshot
