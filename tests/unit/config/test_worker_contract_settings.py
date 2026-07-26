from __future__ import annotations

from pathlib import Path

import yaml


def test_worker_contract_settings_present() -> None:
    cfg = yaml.safe_load(
        Path("settings/mahavishnu.yaml").read_text(encoding="utf-8")
    )
    assert "worker_contract" in cfg
    wc = cfg["worker_contract"]
    assert wc["enabled"] is False
    assert wc["default_session_mode"] == "managed_tmux"
    assert wc["max_wait_ms"] == 30_000
