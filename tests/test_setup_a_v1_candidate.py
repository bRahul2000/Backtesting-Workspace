"""The frozen research manifest must remain tied to original Setup A defaults."""
import json
import subprocess
from dataclasses import asdict

import pytest

from research.exness_setup_a_validation import SETTINGS
from research.setup_a_v1_candidate import (
    FROZEN_FILE, ROOT, SOURCE_COMMIT, SOURCE_TAG, _plain,
    canonical_bytes, expected_manifest, freeze_hash, validate_frozen, write_once,
)
from strategies.btc_v2_setup_a import SETUP_ID, SetupAParameters


def test_frozen_configuration_matches_active_setup_a_defaults_and_research_account():
    frozen = validate_frozen()
    assert frozen["strategy_name"] == "BTC Setup A V1 Research Candidate"
    assert frozen["setup_id"] == SETUP_ID
    assert frozen["strategy_parameters"] == _plain(asdict(SetupAParameters()))
    assert frozen["audited_research_execution"] == _plain(asdict(SETTINGS))
    assert frozen == expected_manifest()


def test_setup_b_and_volatility_gate_are_excluded():
    frozen = validate_frozen()
    assert frozen["setup_a_enabled"] is True
    assert frozen["setup_b_enabled"] is False
    assert frozen["volatility_gate_enabled"] is False
    assert frozen["strategy_parameters"]["reward_multiple"] == 3.0
    assert frozen["status"] == "RESEARCH FROZEN"
    assert frozen["live_approved"] is False


def test_serialization_and_hash_stability():
    frozen = validate_frozen()
    reconstructed = json.loads(json.dumps(frozen, sort_keys=False, ensure_ascii=False))
    assert reconstructed == frozen
    assert canonical_bytes(reconstructed) == canonical_bytes(frozen)
    assert freeze_hash(reconstructed) == frozen["freeze_hash_sha256"]
    assert len(frozen["freeze_hash_sha256"]) == 64
    assert json.loads(FROZEN_FILE.read_text()) == frozen


def test_source_checkpoint_and_checksums_are_locked():
    frozen = validate_frozen()
    assert frozen["source_commit"] == SOURCE_COMMIT
    assert frozen["source_tag"] == SOURCE_TAG
    assert subprocess.check_output(
        ["git", "rev-parse", SOURCE_TAG], cwd=ROOT, text=True).strip() == SOURCE_COMMIT
    assert "reference/BTC_Pullback_Trend_Breakout_V2_2_0.pine" in frozen["source_files_sha256"]
    assert "strategies/btc_v2_setup_a.py" in frozen["source_files_sha256"]


def test_write_once_refuses_silent_change(tmp_path):
    target = tmp_path / "frozen_strategy.json"
    original = write_once(target)
    assert write_once(target) == original
    tampered = original.copy()
    tampered["setup_b_enabled"] = True
    target.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="hash mismatch"):
        write_once(target)
