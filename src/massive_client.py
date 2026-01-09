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
    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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

        # Handle HTTP errors explicitly so we can treat 404 as "no data"
        if resp.status_code == 404:
            # This is very common for symbols with no options coverage.
            logger.warning(
                "Massive API 404 (no data) | url=%s | body=%s",
                resp.request.url,
                resp.text[:500],
            )
            # Return an empty "results" shape so callers can decide what to do.
            return {"results": []}

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Massive API request failed | url=%s | status=%s | body=%s",
                resp.request.url,
                resp.status_code,
                resp.text[:500],
            )
            raise

        try:
            return resp.json()
        except ValueError as exc:
            logger.error(
                "Massive API returned invalid JSON | url=%s | error=%s",
                resp.request.url,
                exc,
            )
            raise MassiveAPIError(
                f"Invalid JSON from Massive for {resp.request.url}"
            ) from exc

    # -------------------------------------------------------------------------
    # High-level methods
    # -------------------------------------------------------------------------

    def get_option_chain_snapshot(
        self,
        symbol: str,
        contract_type: Optional[str] = None,
        limit: int = 250,
    ) -> Optional[OptionChainSnapshotResponse]:
        """
        Fetch the option chain snapshot for a given underlying symbol.

        Massive docs (examples):

            GET /v3/snapshot/options/{underlyingAsset}

        e.g.
            /v3/snapshot/options/SPY
            /v3/snapshot/options/I:SPX

        We keep this method aligned with that endpoint.
        """
        params: Dict[str, Any] = {"limit": limit}
        if contract_type:
            # Massive expects "calls" / "puts" here
            params["contract_type"] = contract_type

        try:
            data = self._get(f"/v3/snapshot/options/{symbol}", params=params)
        except (httpx.RequestError, httpx.HTTPStatusError, RetryError) as exc:
            # Network issues, non-404 HTTP errors, etc.
            raise MassiveAPIError(str(exc)) from exc

        # If 404/no-data, _get returns {"results": []}
        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            logger.info(
                "Massive option chain empty | ticker=%s | reason=no results",
                symbol,
            )
            return None

        try:
            snapshot = OptionChainSnapshotResponse.parse_obj(data)
        except Exception as exc:
            logger.exception(
                "Failed to parse option chain snapshot | ticker=%s", symbol
            )
            raise MassiveAPIError(
                f"Failed to parse option chain snapshot for {symbol}: {exc}"
            ) from exc

        # Extra guardrail logging so you can see how much data you got
        contracts_count = 0
        try:
            first_result = snapshot.results[0] if snapshot.results else None
            if first_result and first_result.contracts is not None:
                contracts_count = len(first_result.contracts)
        except Exception:
            # Don't let logging issues break the worker
            logger.exception(
                "Error computing contracts count for ticker=%s", symbol
            )

        logger.info(
            "Massive option chain fetched | ticker=%s | contracts=%s",
            symbol,
            contracts_count,
        )
        return snapshot