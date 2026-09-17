"""Resume Bitstamp history, then rebuild the frozen Setup B research report."""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from research.setup_b_history_baseline import build_report
from services.bitstamp import BitstampAPIError, BitstampClient, latest_complete_candle_open
from services.history import sync_btc_history


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2023-01-01", help="Primary UTC history start")
    parser.add_argument("--older-start", default="2021-01-01", help="Earlier UTC extension")
    parser.add_argument("--skip-older", action="store_true")
    args = parser.parse_args()
    primary_start = pd.Timestamp(args.start, tz="UTC")
    older_start = pd.Timestamp(args.older_start, tz="UTC")
    latest = latest_complete_candle_open()
    client = BitstampClient(timeout_seconds=10, max_retries=2,
                            backoff_seconds=0.7, min_request_interval_seconds=0.2)

    def progress(done: int, total: int, saved: int) -> None:
        if done == 1 or done % 10 == 0 or done == total:
            print(f"checkpoint {done}/{total}: {saved:,} saved candles", flush=True)

    errors = []
    try:
        primary = sync_btc_history(primary_start, latest, client=client,
                                   progress=progress)
        print(f"Primary range: {primary.saved_candles:,} saved; "
              f"{primary.remaining_candles:,} requested timestamps still missing.")
    except BitstampAPIError as exc:
        errors.append(f"Primary 2023+ request stopped: {exc}")
        print(errors[-1], file=sys.stderr)

    if not args.skip_older:
        older_end = primary_start - pd.Timedelta(minutes=15)
        try:
            probe_end = min(older_start + pd.Timedelta(days=1) - pd.Timedelta(minutes=15),
                            older_end)
            probe = client.download_ohlc(older_start, probe_end)
            if probe.empty:
                print("Bitstamp returned no candles for the 2021 probe; earlier extension skipped.")
            else:
                older = sync_btc_history(older_start, older_end, client=client,
                                         progress=progress)
                print(f"Older range: {older.saved_candles:,} saved; "
                      f"{older.remaining_candles:,} requested timestamps still missing.")
        except BitstampAPIError as exc:
            errors.append(f"Older 2021 extension unavailable: {exc}")
            print(errors[-1], file=sys.stderr)

    summary = build_report()
    print(f"Largest continuous baseline: {summary['data_start']} through "
          f"{summary['data_end']}; {summary['candles']:,} candles; "
          f"{summary['metrics']['total_trades']} completed trades.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
