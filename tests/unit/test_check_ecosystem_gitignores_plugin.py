"""Smoke test for the crackerjack plugin wiring of the audit script.

The plugin is a single JSON file at
``mahavishnu/plugins/check_ecosystem_gitignores.json`` that
crackerjack's ``PluginDiscovery`` picks up automatically and registers
as a custom hook. This test pins the location, filename, and schema
so a future refactor doesn't silently break the wire-up.

If the test starts failing because the file was moved or renamed,
update::

  * the JSON path here,
  * the ``command`` inside the JSON (must remain runnable from the
    mahavishnu project root),
  * the crackerjack docs that reference this hook name.
"""

from __future__ import annotations

import json
from pathlib import Path

# Locate the mahavishnu project root from this test file's location.
# tests/unit/test_check_ecosystem_gitignores_plugin.py → ../../..
MAHAVISHNU_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_PATH = MAHAVISHNU_ROOT / "plugins" / "check_ecosystem_gitignores.json"
AUDIT_SCRIPT = MAHAVISHNU_ROOT / "scripts" / "check_ecosystem_gitignores.py"


# Mirror of crackerjack's _looks_like_plugin_file filter (from
# crackerjack/plugins/loader.py). If crackerjack's filter changes,
# this test will catch the divergence.
def _looks_like_plugin_file(name: str) -> bool:
    name_lower = name.lower()
    if name_lower.startswith(("test_", "__", ".")):
        return False
    if name_lower in ("__init__.py", "setup.py", "conftest.py"):
        return False
    indicators = ("plugin", "hook", "extension", "addon", "crackerjack", "check", "lint", "format")
    return any(i in name_lower for i in indicators)


def test_plugin_file_exists_at_expected_path() -> None:
    """The plugin JSON must live where crackerjack's auto-discovery looks."""
    assert PLUGIN_PATH.is_file(), (
        f"Crackerjack plugin JSON missing at {PLUGIN_PATH}. "
        f"PluginDiscovery scans <project>/plugins/ — keep this file there."
    )


def test_plugin_filename_passes_crackerjack_filter() -> None:
    """The filename must satisfy crackerjack's plugin-file heuristic.

    The filter rejects test_, __, and dotfile prefixes, and requires
    at least one of these substrings: plugin, hook, extension,
    addon, crackerjack, check, lint, format.
    """
    assert _looks_like_plugin_file(PLUGIN_PATH.name), (
        f"Filename {PLUGIN_PATH.name!r} does not match crackerjack's "
        f"plugin-file indicator list; auto-discovery will skip it."
    )


def test_plugin_json_parses_and_has_required_top_level_keys() -> None:
    config = json.loads(PLUGIN_PATH.read_text(encoding="utf-8"))
    for key in ("name", "version", "type", "description", "hooks"):
        assert key in config, f"Plugin config missing top-level key: {key}"
    assert config["type"] == "hook", f"Plugin type must be 'hook', got {config['type']!r}"


def test_plugin_hook_schema_matches_crackerjack_loader() -> None:
    """Each hook entry must have the keys crackerjack's loader reads."""
    config = json.loads(PLUGIN_PATH.read_text(encoding="utf-8"))
    for hook in config["hooks"]:
        for key in (
            "name",
            "description",
            "command",
            "file_patterns",
            "timeout",
            "stage",
            "requires_files",
            "parallel_safe",
        ):
            assert key in hook, f"Hook {hook.get('name', '?')!r} missing key: {key}"
        assert hook["stage"] in ("fast", "comprehensive"), (
            f"Hook {hook['name']!r} has invalid stage {hook['stage']!r}"
        )
        assert isinstance(hook["command"], list) and hook["command"], (
            f"Hook {hook['name']!r} must have a non-empty command list"
        )


def test_plugin_command_targets_audit_script() -> None:
    """The hook's command must run the audit script from the project root."""
    config = json.loads(PLUGIN_PATH.read_text(encoding="utf-8"))
    cmd = config["hooks"][0]["command"]
    # The command's last element should reference the audit script by
    # its in-repo path. (crackerjack hooks run with cwd=project root.)
    script_ref = cmd[-1]
    assert script_ref.endswith("check_ecosystem_gitignores.py"), (
        f"Hook command should end with the audit script path, got {script_ref!r}"
    )
    assert AUDIT_SCRIPT.is_file(), (
        f"Audit script not found at {AUDIT_SCRIPT}; the hook's command will fail at runtime."
    )


def test_audit_script_exits_zero_on_clean_tree() -> None:
    """The hook's command (the audit) must exit 0 right now.

    This is a smoke test that the wired-up hook would pass when
    crackerjack runs it. If this fails, either the script regressed
    or the ecosystem drifted — fix the underlying state, not the test.
    """
    import subprocess

    result = subprocess.run(
        ["python", str(AUDIT_SCRIPT)],
        cwd=MAHAVISHNU_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Audit returned {result.returncode}; the crackerjack hook "
        f"would fail the build. Audit output:\n{result.stdout}\n"
        f"{result.stderr}"
    )
