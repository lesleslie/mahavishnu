"""Tests for the consolidated Bifrost harness toggle.

req: REQ-BIFROST-025, REQ-BIFROST-026, REQ-BIFROST-027, REQ-BIFROST-028, REQ-BIFROST-029
"""

from __future__ import annotations

import dataclasses
import json
from typing import TYPE_CHECKING, Any

import pytest
import typer

from mahavishnu.bifrost import models, toggles

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _no_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts with the operator gate off unless it sets it."""
    monkeypatch.delenv(toggles.GATE_ENV, raising=False)


@pytest.fixture(autouse=True)
def _no_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ambient virtual key unless a test supplies one."""
    monkeypatch.delenv(models.VIRTUAL_KEY_ENV, raising=False)


@pytest.fixture
def vk(monkeypatch: pytest.MonkeyPatch) -> str:
    """Supply the virtual key through the environment, as operators do."""
    monkeypatch.setenv(models.VIRTUAL_KEY_ENV, "sk-vk-TEST")
    return "sk-vk-TEST"


@pytest.fixture
def backup_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect backup writes into tmp_path; never touch the real ~/.config."""
    target = tmp_path / "backups"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(models, "BIFROST_BACKUP_DIR", target)
    return target


def _harness(key: str, settings_path: Path) -> models.HarnessDescriptor:
    return dataclasses.replace(models.resolve_harness(key), settings_path=settings_path)


def _write(path: Path, body: dict[str, Any]) -> None:
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_cc_writes_url_and_appends_virtual_key(tmp_path: Path, backup_dir: Path, vk: str) -> None:
    """req: REQ-BIFROST-026 -- x-bf-vk appended, other headers preserved."""
    settings = tmp_path / "settings.json"
    _write(
        settings,
        {
            "env": {
                "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic",
                "ANTHROPIC_CUSTOM_HEADERS": "X-Other: keepme",
            }
        },
    )
    toggles.apply(_harness("cc", settings), "bifrost")

    env = _read(settings)["env"]
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8471/anthropic"
    assert env["ANTHROPIC_CUSTOM_HEADERS"] == "X-Other: keepme\nx-bf-vk: sk-vk-TEST"


def test_cc_repeat_does_not_duplicate_header(tmp_path: Path, backup_dir: Path, vk: str) -> None:
    """req: REQ-BIFROST-026 -- a second apply must not double the header."""
    settings = tmp_path / "settings.json"
    _write(settings, {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8471/anthropic"}})
    harness = _harness("cc", settings)

    toggles.apply(harness, "bifrost")
    toggles.apply(harness, "bifrost")

    assert _read(settings)["env"]["ANTHROPIC_CUSTOM_HEADERS"] == "x-bf-vk: sk-vk-TEST"


def test_direct_restores_url_and_removes_our_header(
    tmp_path: Path, backup_dir: Path, vk: str
) -> None:
    """req: REQ-BIFROST-026 -- round-trip removes exactly what we added."""
    settings = tmp_path / "settings.json"
    _write(settings, {"env": {"ANTHROPIC_CUSTOM_HEADERS": "X-Other: keepme"}})
    harness = _harness("cc", settings)

    toggles.apply(harness, "bifrost")
    toggles.apply(harness, "direct")

    env = _read(settings)["env"]
    assert "ANTHROPIC_BASE_URL" not in env
    assert env["ANTHROPIC_CUSTOM_HEADERS"] == "X-Other: keepme"
    assert not (backup_dir / "cc-url-backup.txt").exists()


def test_qwen_writes_model_generation_config_headers(
    tmp_path: Path, backup_dir: Path, vk: str
) -> None:
    """req: REQ-BIFROST-027 -- runtime-model sink, not modelProviders."""
    settings = tmp_path / "settings.json"
    _write(settings, {"env": {"OPENAI_BASE_URL": "https://old.example/v1"}})

    toggles.apply(_harness("qwen", settings), "bifrost")

    body = _read(settings)
    assert body["env"]["OPENAI_BASE_URL"] == "http://127.0.0.1:8471/v1"
    headers = body["model"]["generationConfig"]["customHeaders"]
    assert headers["x-bf-vk"] == "sk-vk-TEST"


def test_backup_never_persists_the_credential(tmp_path: Path, backup_dir: Path, vk: str) -> None:
    """Security: a plaintext backup must never park a secret on disk."""
    settings = tmp_path / "settings.json"
    _write(settings, {})
    harness = _harness("cc", settings)

    toggles.apply(harness, "bifrost")  # nothing prior to back up
    # Re-point at a different host so a second backup is written *while a
    # credential is configured* -- the case that would leak a secret.
    toggles.apply(harness, "bifrost", host="10.0.0.9")

    raw = (backup_dir / "cc-url-backup.txt").read_text(encoding="utf-8")
    assert "sk-vk-TEST" not in raw
    assert "credential" not in json.loads(raw)
    assert json.loads(raw)["credential_present"] is True


def test_backup_file_is_owner_only(tmp_path: Path, backup_dir: Path, vk: str) -> None:
    """Security: the backup file must not be world-readable."""
    settings = tmp_path / "settings.json"
    _write(settings, {})
    toggles.apply(_harness("cc", settings), "bifrost")

    mode = (backup_dir / "cc-url-backup.txt").stat().st_mode & 0o777
    assert mode == 0o600


def test_refuses_to_clobber_existing_credential(tmp_path: Path, backup_dir: Path, vk: str) -> None:
    """Security: never destroy a key we deliberately do not back up."""
    settings = tmp_path / "settings.json"
    _write(settings, {"env": {"ANTHROPIC_CUSTOM_HEADERS": "x-bf-vk: sk-vk-PRECIOUS"}})
    harness = _harness("cc", settings)

    with pytest.raises(typer.Exit):
        toggles.apply(harness, "bifrost")

    assert _read(settings)["env"]["ANTHROPIC_CUSTOM_HEADERS"] == "x-bf-vk: sk-vk-PRECIOUS"


def test_force_overwrites_existing_credential(tmp_path: Path, backup_dir: Path, vk: str) -> None:
    """Security: --force is the explicit escape hatch."""
    settings = tmp_path / "settings.json"
    _write(settings, {"env": {"ANTHROPIC_CUSTOM_HEADERS": "x-bf-vk: sk-vk-PRECIOUS"}})
    harness = _harness("cc", settings)

    toggles.apply(harness, "bifrost", force=True)

    assert _read(settings)["env"]["ANTHROPIC_CUSTOM_HEADERS"] == "x-bf-vk: sk-vk-TEST"


def test_cli_exposes_no_virtual_key_argv_option() -> None:
    """Security: argv is world-visible via ps and lands in shell history."""
    import inspect

    from mahavishnu.cli.bifrost_cli import bifrost_app

    for command in bifrost_app.registered_commands:
        params = inspect.signature(command.callback).parameters
        assert "virtual_key" not in params, (
            f"{command.name} exposes a --virtual-key option; use ${models.VIRTUAL_KEY_ENV} "
            f"or --virtual-key-file instead."
        )


def test_gate_blocks_rewrite(
    tmp_path: Path, backup_dir: Path, monkeypatch: pytest.MonkeyPatch, vk: str
) -> None:
    """req: REQ-BIFROST-029 -- opt-out must hold in the Python path too."""
    settings = tmp_path / "settings.json"
    _write(settings, {"env": {"ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic"}})
    before = settings.read_text(encoding="utf-8")

    monkeypatch.setenv(toggles.GATE_ENV, "1")
    toggles.apply(_harness("cc", settings), "bifrost")

    assert settings.read_text(encoding="utf-8") == before


def test_legacy_bare_url_backup_is_restored(tmp_path: Path, backup_dir: Path) -> None:
    """Backups written by the retired scripts were bare URLs; still honoured."""
    settings = tmp_path / "settings.json"
    _write(settings, {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8471/anthropic"}})
    (backup_dir / "cc-url-backup.txt").write_text(
        "https://legacy.example/anthropic\n", encoding="utf-8"
    )

    toggles.apply(_harness("cc", settings), "direct")

    assert _read(settings)["env"]["ANTHROPIC_BASE_URL"] == "https://legacy.example/anthropic"


def test_legacy_credential_backup_is_not_restyored(tmp_path: Path, backup_dir: Path) -> None:
    """Security: a pre-fix backup holding a secret must not be replayed."""
    settings = tmp_path / "settings.json"
    _write(settings, {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8471/anthropic"}})
    (backup_dir / "cc-url-backup.txt").write_text(
        json.dumps({"url": "https://legacy/anthropic", "credential": "sk-vk-OLD"}),
        encoding="utf-8",
    )

    toggles.apply(_harness("cc", settings), "direct")

    env = _read(settings)["env"]
    assert env["ANTHROPIC_BASE_URL"] == "https://legacy/anthropic"
    assert "ANTHROPIC_CUSTOM_HEADERS" not in env


def test_bifrost_without_key_warns(tmp_path: Path, backup_dir: Path, capsys) -> None:
    """req: REQ-BIFROST-028 -- missing key is surfaced, not silently written."""
    settings = tmp_path / "settings.json"
    _write(settings, {})

    toggles.apply(_harness("cc", settings), "bifrost")

    assert "WARNING" in capsys.readouterr().err
    assert toggles.credential_configured(_harness("cc", settings)) is False


def test_key_file_supplies_virtual_key(
    tmp_path: Path, backup_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """req: REQ-BIFROST-028 -- file indirection avoids putting it in argv."""
    settings = tmp_path / "settings.json"
    _write(settings, {})
    key_file = tmp_path / "vk.txt"
    key_file.write_text("sk-vk-FILE\n", encoding="utf-8")

    toggles.apply(_harness("cc", settings), "bifrost", key_file=key_file)

    assert toggles.credential_configured(_harness("cc", settings)) is True
