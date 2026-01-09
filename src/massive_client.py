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

from .models import OptionChainSnapshot, OptionChainSnapshotResponse


class MassiveAPIError(Exception):
    pass


class MassiveClient:
    def __init__(self, api_key: str, base_url: str, logger: Optional[logging.Logger] = None) -> None:
        self._client = httpx.Client(
            base_url=base_url,
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
        response = self._client.get(url)
        if response.status_code == 429 or response.status_code >= 500:
            raise httpx.HTTPStatusError(
                f"Retryable error {response.status_code}",
                request=response.request,
                response=response,
            )
        response.raise_for_status()
        return response

    def get_option_chain_snapshot(self, ticker: str) -> OptionChainSnapshot:
        endpoint = f"/v3/options/snapshots/option-chain-snapshot/{ticker}"
        try:
            response = self._get(endpoint)
            payload = response.json()
            parsed = OptionChainSnapshotResponse.parse_obj(payload)
            return parsed.data
        except (httpx.RequestError, httpx.HTTPStatusError, RetryError) as exc:
            self._logger.error("Massive API request failed | ticker=%s | error=%s", ticker, exc)
            raise MassiveAPIError(str(exc)) from exc
        except Exception as exc:
            self._logger.exception("Unexpected Massive API error | ticker=%s", ticker)
            raise MassiveAPIError(str(exc)) from exc
