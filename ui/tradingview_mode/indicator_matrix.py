"""Write docs/INDICATOR_CAPABILITY_MATRIX.json from the indicator registry (a test keeps it in sync).

    python -m ui.tradingview_mode.indicator_matrix
"""
import json
from pathlib import Path

from .indicators import capability_matrix

PATH = Path(__file__).resolve().parents[2] / "docs" / "INDICATOR_CAPABILITY_MATRIX.json"

if __name__ == "__main__":
    PATH.write_text(json.dumps(capability_matrix(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {PATH}")
