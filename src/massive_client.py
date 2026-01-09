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

from .config import load_settings
from .models import OptionChainSnapshot, OptionChainSnapshotResponse

settings = load_settings()


class MassiveAPIError(Exception):
    pass


class MassiveClient:
    def __init__(self, api_key: str, base_url: str, logger: Optional[logging.Logger] = None) -> None:
        """
        Thin Massive API client.

        NOTE:
        - We now expect base_url to be something like 'https://api.massive.app'
        - The correct option chain snapshot endpoint (per Massive docs) is:
              GET /v3/snapshot/options/{underlying_ticker}
        """
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(5.0),
            headers={"Authorization": f"Bearer {api_key}"},
        )
        self._logger = logger or logging.getLogger(__name__)

    def close(self) -> None:
        self._client.close()

    @retry(
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        reraise=True,
    )
    def _get(self, url: str) -> httpx.Response:
        # `url` here is a path like '/v3/snapshot/options/SPY'
        self._logger.info("Massive API request | url=%s", url)
        response = self._client.get(url)
        if response.status_code in (429,) or response.status_code >= 500:
            # Mark retryable HTTP errors
            raise httpx.HTTPStatusError(
                f"Retryable error {response.status_code}",
                request=response.request,
                response=response,
            )
        response.raise_for_status()
        return response

    def get_option_chain_snapshot(self, ticker: str) -> OptionChainSnapshot:
        """
        Fetch the option chain snapshot for a given underlying.

        Correct endpoint:
            GET /v3/snapshot/options/{ticker}
        Example final URL (with base_url = https://api.massive.app):
            https://api.massive.app/v3/snapshot/options/SPY
        """
        symbol = ticker.upper().strip()
        endpoint = f"/v3/snapshot/options/{symbol}"

        try:
            response = self._get(endpoint)
            payload = response.json()
            parsed = OptionChainSnapshotResponse.parse_obj(payload)
            # Assuming `data` field holds the actual OptionChainSnapshot per your models
            chain = parsed.data
            self._logger.info(
                "Massive option chain fetched | ticker=%s | contracts=%s",
                symbol,
                len(chain.contracts) if getattr(chain, "contracts", None) is not None else "unknown",
            )
            return chain
        except (httpx.RequestError, httpx.HTTPStatusError, RetryError) as exc:
            self._logger.error(
                "Massive API request failed | ticker=%s | error=%s",
                symbol,
                exc,
            )
            raise MassiveAPIError(str(exc)) from exc
        except Exception as exc:
            self._logger.exception("Unexpected Massive API error | ticker=%s", symbol)
            raise MassiveAPIError(str(exc)) from exc
