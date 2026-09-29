# Gold V2 raw MT5 snapshot (local, immutable)

This folder holds exports copied **read-only** from MT5 Common Files on 2026-09-29: M1 bars, tick samples and probe
outputs from Exness-MT5Trial5.

- **Hashes.** Every file was hashed before parsing (`SHA256SUMS`); `MANIFEST.tsv` lists names, sizes and hashes.
- **Not in git.** The large `*.csv` payloads (≈ 603 MB) are **not committed** (`.gitignore`) and must not be edited
  or deleted.
- **Verify before any analysis:** `shasum -a 256 -c SHA256SUMS`.
- **Regenerating.** Run the exporters in `research/gold_v2/tools/` (exact MQL5 source; see `tools/SHA256SUMS`), then
  `research/gold_v2/data/audit_v2_data.py snapshot`. Broker-side history can change, so compare against this
  manifest.
- **Sealed rows.** None: the exporters refuse sealed dates, and a text scan found 0.
