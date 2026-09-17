from __future__ import annotations

import math
import time
from typing import Callable, Optional

import pandas as pd
import requests

from utils.data_validation import DataValidationError, merge_ohlcv, prepare_ohlcv


BITSTAMP_OHLC_URL = "https://www.bitstamp.net/api/v2/ohlc/btcusd/"
BITSTAMP_STEP_SECONDS = 900
BITSTAMP_MAX_CANDLES = 1000

ProgressCallback = Callable[[int, int, int], None]


class BitstampAPIError(RuntimeError):
    """A user-facing Bitstamp download error."""


def latest_complete_candle_open(now: Optional[pd.Timestamp] = None) -> pd.Timestamp:
    """Return the UTC open time of the latest fully closed 15-minute candle."""
    current = now if now is not None else pd.Timestamp.now(tz="UTC")
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    else:
        current = current.tz_convert("UTC")
    return current.floor(f"{BITSTAMP_STEP_SECONDS}s") - pd.Timedelta(
        seconds=BITSTAMP_STEP_SECONDS
    )


class BitstampClient:
    def __init__(
        self,
        timeout_seconds: float = 15.0,
        max_retries: int = 3,
        backoff_seconds: float = 0.6,
        min_request_interval_seconds: float = 0.15,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.min_request_interval_seconds = min_request_interval_seconds
        self._last_request_started: float | None = None
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": "BTC-Strategy-Backtester/1.0 (+local Streamlit app)"}
        )

    def _request_chunk(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        limit: int,
    ) -> pd.DataFrame:
        params = {
            "step": BITSTAMP_STEP_SECONDS,
            "limit": min(max(int(limit), 1), BITSTAMP_MAX_CANDLES),
            "start": int(start.timestamp()),
            "end": int(end.timestamp()),
            "exclude_current_candle": "true",
        }

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                if self._last_request_started is not None:
                    elapsed = time.monotonic() - self._last_request_started
                    if elapsed < self.min_request_interval_seconds:
                        time.sleep(self.min_request_interval_seconds - elapsed)
                self._last_request_started = time.monotonic()
                response = self.session.get(
                    BITSTAMP_OHLC_URL,
                    params=params,
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise requests.HTTPError(
                        f"temporary Bitstamp response ({response.status_code})",
                        response=response,
                    )
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("data", {}).get("ohlc")
                if not isinstance(rows, list):
                    reason = payload.get("reason") or payload.get("response_explanation")
                    raise BitstampAPIError(reason or "Bitstamp returned an unexpected response.")
                if not rows:
                    return pd.DataFrame(
                        columns=["timestamp", "open", "high", "low", "close", "volume"]
                    )
                prepared, _ = prepare_ohlcv(pd.DataFrame(rows))
                return prepared[
                    (prepared["timestamp"] >= start) & (prepared["timestamp"] <= end)
                ].reset_index(drop=True)
            except BitstampAPIError:
                raise
            except (requests.Timeout, requests.ConnectionError, requests.HTTPError, ValueError) as exc:
                last_error = exc
                retryable = not isinstance(exc, requests.HTTPError) or (
                    exc.response is not None
                    and (exc.response.status_code == 429 or exc.response.status_code >= 500)
                )
                if not retryable or attempt >= self.max_retries:
                    break
                time.sleep(self.backoff_seconds * (2**attempt))
            except DataValidationError as exc:
                raise BitstampAPIError(f"Bitstamp data validation failed: {exc}") from exc

        raise BitstampAPIError(
            f"Bitstamp request failed after {self.max_retries + 1} attempts: {last_error}"
        ) from last_error

    def download_ohlc(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> pd.DataFrame:
        """Download an inclusive UTC range in API-safe chronological chunks."""
        start = pd.Timestamp(start)
        end = pd.Timestamp(end)
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        end = end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC")
        start = start.ceil(f"{BITSTAMP_STEP_SECONDS}s")
        end = min(end.floor(f"{BITSTAMP_STEP_SECONDS}s"), latest_complete_candle_open())

        if start > end:
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        candle_count = int((end - start).total_seconds() // BITSTAMP_STEP_SECONDS) + 1
        total_chunks = math.ceil(candle_count / BITSTAMP_MAX_CANDLES)
        chunks: list[pd.DataFrame] = []
        chunk_start = start
        received_rows = 0

        for chunk_number in range(1, total_chunks + 1):
            chunk_end = min(
                chunk_start
                + pd.Timedelta(seconds=BITSTAMP_STEP_SECONDS * (BITSTAMP_MAX_CANDLES - 1)),
                end,
            )
            chunk_limit = int(
                (chunk_end - chunk_start).total_seconds() // BITSTAMP_STEP_SECONDS
            ) + 1
            chunk = self._request_chunk(chunk_start, chunk_end, chunk_limit)
            chunks.append(chunk)
            received_rows += len(chunk)
            if progress_callback:
                progress_callback(chunk_number, total_chunks, received_rows)
            chunk_start = chunk_end + pd.Timedelta(seconds=BITSTAMP_STEP_SECONDS)

        combined = merge_ohlcv(*chunks)
        return combined[
            (combined["timestamp"] >= start) & (combined["timestamp"] <= end)
        ].reset_index(drop=True)
