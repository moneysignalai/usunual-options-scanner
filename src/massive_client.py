from __future__ import annotations

import logging
from typing import Optional

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

    We centralize:
    - base URL handling (always https://api.massive.com)
    - auth header (MASSIVE_API_KEY)
    - retry policy for transient network failures
    - logging of all outbound requests
    """

    def __init__(self, settings: Optional[Settings] = None, client: Optional[httpx.Client] = None) -> None:
        self._settings = settings or load_settings()
        base_url = self._settings.massive_base_url.rstrip("/")

        # Single shared HTTP client with base_url + auth header
        self._client = client or httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {self._settings.massive_api_key}",
                "Accept": "application/json",
            },
            timeout=httpx.Timeout(10.0, connect=5.0),
        )

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            logger.exception("Error while closing Massive HTTP client")

    # ---- low-level HTTP helper -------------------------------------------------

    @retry(
        reraise=True,
        retry=retry_if_exception_type(httpx.RequestError),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
    )
    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        """
        Perform a GET to the Massive API with basic retries and logging.

        `path` MUST start with `/v3/…` – we do **not** include `/v1/` in the base URL.
        """
        logger.info("Massive API request | url=%s | params=%s", path, params)
        try:
            resp = self._client.get(path, params=params)
        except httpx.RequestError as exc:
            logger.error("Massive API network error | url=%s | error=%s", path, exc)
            raise

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            # This is what you were seeing: 404s in Render logs
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
            logger.error("Massive API returned invalid JSON | url=%s | error=%s", resp.request.url, exc)
            raise MassiveAPIError(f"Invalid JSON from Massive for {resp.request.url}") from exc

    # ---- high-level methods ----------------------------------------------------

    def get_option_chain_snapshot(
        self,
        symbol: str,
        contract_type: Optional[str] = None,
        limit: int = 250,
    ) -> Optional[OptionChainSnapshotResponse]:
        """
        Fetch the option chain snapshot for a given underlying symbol.

        This uses the documented Massive endpoint:

            GET /v3/snapshot/options/{underlyingAsset}

        Example:
            /v3/snapshot/options/SPY

        We **do not** call any of the older `/options/snapshots/option-chain-snapshot` paths.
        """
        params: dict = {"limit": limit}
        if contract_type:
            # Massive expects "calls" / "puts" here
            params["contract_type"] = contract_type

        try:
            data = self._get(f"/v3/snapshot/options/{symbol}", params=params)
        except (httpx.RequestError, httpx.HTTPStatusError, RetryError) as exc:
            raise MassiveAPIError(str(exc)) from exc

        try:
            snapshot = OptionChainSnapshotResponse.parse_obj(data)
        except Exception as exc:
            logger.exception("Failed to parse option chain snapshot | ticker=%s", symbol)
            raise MassiveAPIError(f"Failed to parse option chain snapshot for {symbol}: {exc}") from exc

        # Optional: extra guardrail logging so you can see how much data you got
        count = 0
        try:
            if snapshot.results and snapshot.results[0].contracts is not None:
                count = len(snapshot.results[0].contracts)
        except Exception:
            # Don't let logging issues break the worker
            logger.exception("Error computing contracts count for ticker=%s", symbol)

        logger.info(
            "Massive option chain fetched | ticker=%s | contracts=%s",
            symbol,
            count,
        )
        return snapshot
