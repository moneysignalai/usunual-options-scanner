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


class TelegramDeliveryError(Exception):
    pass


class TelegramClient:
    def __init__(self, token: str, chat_id: str, logger: Optional[logging.Logger] = None) -> None:
        self._token = token
        self._chat_id = chat_id
        self._logger = logger or logging.getLogger(__name__)
        self._client = httpx.Client(timeout=httpx.Timeout(5.0))

    def close(self) -> None:
        self._client.close()

    @retry(
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        reraise=True,
    )
    def _post(self, payload: dict) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        response = self._client.post(url, data=payload)
        response.raise_for_status()

    def send_message(self, text: str) -> None:
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        try:
            self._post(payload)
        except (httpx.RequestError, httpx.HTTPStatusError, RetryError) as exc:
            self._logger.error("Telegram delivery failed | error=%s", exc)
            raise TelegramDeliveryError(str(exc)) from exc
        except Exception as exc:
            self._logger.exception("Unexpected Telegram error")
            raise TelegramDeliveryError(str(exc)) from exc
