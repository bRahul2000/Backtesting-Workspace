"""python -m ui.tradingview_mode.pine.parity  -> regenerate fixtures, manual scripts, our outputs, PARITY_REPORT.md."""
from .harness import REPORT, write_all

results = write_all()
for result in results:
    print(f"{result.fixture.name:18} {result.reference.source:20} {result.verdict:13} mismatches={result.mismatches}")
print(f"compared {len(results)} fixture/reference pair(s); wrote {REPORT}")
