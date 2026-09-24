"""Runs the lightweight Node tests for the frontend's presentation-only trade views."""
import shutil
import subprocess
from pathlib import Path

import pytest

TESTS = Path(__file__).with_name("frontend")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_trade_view_filter_sort_navigation_do_not_mutate_rows():
    result = subprocess.run(["node", "--test", str(TESTS)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
