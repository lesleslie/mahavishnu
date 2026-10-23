"""Tests for the consolidated Bifrost harness toggle.

req: REQ-BIFROST-025, REQ-BIFROST-026, REQ-BIFROST-027, REQ-BIFROST-028, REQ-BIFROST-029
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path  # noqa: TC003 -- used at runtime in the gate regression test
import subprocess
from typing import Any

import pytest
import typer

from mahavishnu.bifrost import models, toggles


@pytest.fixture(autouse=True)
def _no_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the gate for tests.

    ``gate_blocks`` probes a sourcing shell, so a developer whose
    ``~/.zshenv`` carries ``BIFROST_CTL_NO_CC_URL_REWRITE=1`` would otherwise
    see every test in this module skip the write and fail. Patch the probe
    itself to report "no gate" rather than mutating the real environment.
    """
    monkeypatch.delenv(toggles.GATE_ENV, raising=False)
    monkeypatch.setattr(toggles, "gate_blocks", lambda _action: False)


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


def test_direct_strips_a_stranded_key_from_a_hand_set_url(
    tmp_path: Path, backup_dir: Path, vk: str
) -> None:
    """req: REQ-BIFROST-026 -- a stranded credential must not outlive Bifrost.

    Live incident: the operator reverted ``ANTHROPIC_BASE_URL`` by hand, which
    made the URL non-Bifrost-managed. ``_action_direct`` bailed out on the URL
    mismatch and left the ``x-bf-vk`` header in place, so Claude Code kept
    sending the Bifrost virtual key to ``api.minimax.io`` on every request --
    handing a local admin credential to a third party.

    The URL stays untouched; only the credential is dropped, because it is
    meaningless off Bifrost and dangerous anywhere else.
    """
    settings = tmp_path / "settings.json"
    _write(
        settings,
        {
            "env": {
                "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic/",
                "ANTHROPIC_CUSTOM_HEADERS": f"{'x-bf-vk'}: {vk}",
            }
        },
    )
    harness = _harness("cc", settings)

    toggles.apply(harness, "direct")

    env = _read(settings)["env"]
    assert env["ANTHROPIC_BASE_URL"] == "https://api.minimax.io/anthropic/", "URL is left alone"
    assert "ANTHROPIC_CUSTOM_HEADERS" not in env, "stranded credential must be removed"


def test_direct_keeps_other_headers_when_stripping_a_stranded_key(
    tmp_path: Path, backup_dir: Path, vk: str
) -> None:
    """The strip is targeted: unrelated headers survive."""
    settings = tmp_path / "settings.json"
    _write(
        settings,
        {
            "env": {
                "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic/",
                "ANTHROPIC_CUSTOM_HEADERS": f"X-Other: keepme\n{'x-bf-vk'}: {vk}",
            }
        },
    )

    toggles.apply(_harness("cc", settings), "direct")

    env = _read(settings)["env"]
    assert env["ANTHROPIC_CUSTOM_HEADERS"] == "X-Other: keepme"


def test_direct_dry_run_reports_the_stranded_key_without_writing(
    tmp_path: Path, backup_dir: Path, vk: str
) -> None:
    """The credential is never backed up, so a dry-run must say so plainly."""
    settings = tmp_path / "settings.json"
    original = {
        "env": {
            "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic/",
            "ANTHROPIC_CUSTOM_HEADERS": f"{'x-bf-vk'}: {vk}",
        }
    }
    _write(settings, original)

    toggles.apply(_harness("cc", settings), "direct", dry_run=True)

    assert _read(settings) == original, "dry-run must not write"


def test_direct_leaves_a_non_bifrost_url_alone_when_no_credential(
    tmp_path: Path, backup_dir: Path
) -> None:
    """No stranded key means no reason to touch the file at all."""
    settings = tmp_path / "settings.json"
    _write(settings, {"env": {"ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic/"}})

    toggles.apply(_harness("cc", settings), "direct")

    assert _read(settings)["env"]["ANTHROPIC_BASE_URL"] == "https://api.minimax.io/anthropic/"


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
    monkeypatch.undo()  # restore the real gate_blocks from the autouse fixture
    settings = tmp_path / "settings.json"
    _write(settings, {"env": {"ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic"}})
    before = settings.read_text(encoding="utf-8")

    monkeypatch.setenv(toggles.GATE_ENV, "1")
    toggles.apply(_harness("cc", settings), "bifrost")

    assert settings.read_text(encoding="utf-8") == before


def test_gate_honoured_when_set_in_zshenv(
    tmp_path: Path, backup_dir: Path, monkeypatch: pytest.MonkeyPatch, vk: str
) -> None:
    """Regression: the gate lives in ``~/.zshenv`` as a *shell-local* var.

    ``BIFROST_CTL_NO_CC_URL_REWRITE=1`` with no ``export`` is invisible to
    ``os.environ``, so a zsh wrapper honoured it while every Python caller
    silently rewrote settings the operator had opted out of. Observed live on
    2026-10-21: the retired ``scripts/bifrost-toggle-claude-url direct``
    stripped ``ANTHROPIC_BASE_URL`` with the gate set. ``gate_blocks`` now
    probes a sourcing shell as well as the environment.
    """
    monkeypatch.undo()
    monkeypatch.delenv(toggles.GATE_ENV, raising=False)

    settings = tmp_path / "settings.json"
    _write(settings, {"env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:8471/anthropic"}})
    before = settings.read_text(encoding="utf-8")

    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        # Simulate a shell that sources .zshenv and finds the gate set.
        if isinstance(cmd, list) and "/bin/zsh" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="1\n", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(toggles.subprocess, "run", fake_run)
    assert toggles.gate_blocks("direct") is True

    toggles.apply(_harness("cc", settings), "direct")
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


# ---------------------------------------------------------------------------
# Qwen model-provider routing
# ---------------------------------------------------------------------------
#
# Qwen Code resolves ``model.name`` against ``modelProviders`` *before* it
# consults ``model.generationConfig``, and when a provider matches it ignores
# the generic block outright:
#
#   Warning: model.generationConfig.customHeaders is ignored for provider
#   model "MiniMax-M3" from modelProviders.anthropic. Move this field to
#   modelProviders.anthropic[].generationConfig ...
#
# A toggle writing only the generic block therefore reports success while the
# harness keeps talking straight to the upstream provider. Verified end to end:
# with the generic block alone, Qwen answered but Bifrost logged no row.


def _qwen_settings(upstream: str = "https://api.minimax.io/anthropic") -> dict[str, Any]:
    return {
        "model": {"name": "MiniMax-M3"},
        "modelProviders": {
            "openai": [{"name": "qwen3.6-plus", "baseUrl": "https://dashscope.aliyuncs.com"}],
            "anthropic": [{"name": "MiniMax-M3", "baseUrl": upstream, "envKey": "MINIMAX_API_KEY"}],
        },
    }


def test_qwen_repoints_the_matching_provider_not_the_env_var(
    tmp_path: Path, backup_dir: Path, vk: str
) -> None:
    settings = tmp_path / "settings.json"
    _write(settings, _qwen_settings())
    harness = _harness("qwen", settings)

    toggles.apply(harness, "bifrost")

    body = _read(settings)
    entry = body["modelProviders"]["anthropic"][0]
    assert entry["baseUrl"] == f"http://{toggles.DEFAULT_BIFROST_HOST}:{toggles.DEFAULT_BIFROST_PORT}/anthropic"
    assert entry["generationConfig"]["customHeaders"]["x-bf-vk"] == vk
    # The OpenAI-protocol provider is a different wire format; repointing it
    # too would be a guess about a model this harness is not using.
    assert body["modelProviders"]["openai"][0]["baseUrl"] == "https://dashscope.aliyuncs.com"
    assert "OPENAI_BASE_URL" not in body.get("env", {})


def test_qwen_header_never_lands_in_the_ignored_generic_block(
    tmp_path: Path, backup_dir: Path, vk: str
) -> None:
    settings = tmp_path / "settings.json"
    _write(settings, _qwen_settings())

    toggles.apply(_harness("qwen", settings), "bifrost")

    body = _read(settings)
    assert "x-bf-vk" not in body["model"].get("generationConfig", {}).get("customHeaders", {})


def test_qwen_direct_restores_the_upstream_provider(
    tmp_path: Path, backup_dir: Path, vk: str
) -> None:
    settings = tmp_path / "settings.json"
    _write(settings, _qwen_settings())
    harness = _harness("qwen", settings)

    toggles.apply(harness, "bifrost")
    toggles.apply(harness, "direct")

    entry = _read(settings)["modelProviders"]["anthropic"][0]
    assert entry["baseUrl"] == "https://api.minimax.io/anthropic"
    assert "x-bf-vk" not in entry.get("generationConfig", {}).get("customHeaders", {})


def test_qwen_without_a_provider_uses_the_generic_block(
    tmp_path: Path, backup_dir: Path, vk: str
) -> None:
    """A bare ``model.name`` with no provider entry is the case the block serves."""
    settings = tmp_path / "settings.json"
    _write(settings, {"model": {"name": "MiniMax-M3"}})
    harness = _harness("qwen", settings)

    toggles.apply(harness, "bifrost")

    body = _read(settings)
    assert body["model"]["generationConfig"]["customHeaders"]["x-bf-vk"] == vk
    assert body["env"]["OPENAI_BASE_URL"].endswith("/v1")


def test_provider_url_follows_the_wire_protocol(
    tmp_path: Path, backup_dir: Path, vk: str
) -> None:
    """The ``anthropic`` provider must not be sent to the OpenAI endpoint."""
    settings = tmp_path / "settings.json"
    _write(
        settings,
        {
            "model": {"name": "qwen3.6-plus"},
            "modelProviders": {
                "openai": [{"name": "qwen3.6-plus", "baseUrl": "https://dashscope.aliyuncs.com"}]
            },
        },
    )

    toggles.apply(_harness("qwen", settings), "bifrost")

    url = _read(settings)["modelProviders"]["openai"][0]["baseUrl"]
    assert url.endswith("/v1")
    assert not url.endswith("/anthropic")


def test_status_names_the_provider_field_it_actually_wrote(
    tmp_path: Path, backup_dir: Path, vk: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reporting ``OPENAI_BASE_URL`` for a provider-routed model is a lie."""
    settings = tmp_path / "settings.json"
    _write(settings, _qwen_settings())
    harness = _harness("qwen", settings)

    toggles.apply(harness, "bifrost")
    toggles.apply(harness, "status")

    out = capsys.readouterr().out
    assert "modelProviders.anthropic.baseUrl: Bifrost" in out
    assert "x-bf-vk header: present" in out
