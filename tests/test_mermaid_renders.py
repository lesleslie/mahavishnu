"""Wave-11 CI guard: every fenced mermaid block in this repo must parse.

Wraps `mahavishnu.tools.mermaid_validator.renderer.find_broken_mermaid_blocks`,
which uses `mermaid.parse()` via Node.js (no chrome dependency). Mirrors
the ratchet pattern established by `tests/unit/test_mcp_tool_inventory.py`
but for diagram syntax instead of tool counts.

The guard needs a Node toolchain: `mermaid-cli` (e.g. `brew install
mermaid-cli`), the `jsdom` dev dep (`npm install`), and `node` itself. When
that toolchain is absent the guard SKIPS rather than fails, because a missing
toolchain means the diagrams were never checked, which is a different thing
from a diagram being broken.

Whether skipping is allowed is a property of the REPO, not of the
environment: see `[tool.mermaid_guard] policy` in pyproject.toml. The
MAHAVISHNU_REQUIRE_MERMAID environment variable can only tighten the policy
to "required"; it can never loosen it, so no environment can disable a guard
the repo requires.

If this test fails, run the validator directly:
    python -c "from mahavishnu.tools.mermaid_validator.renderer import \
        find_broken_mermaid_blocks; [print(e) for e in find_broken_mermaid_blocks()]"
to see the broken blocks per file.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

from mahavishnu.tools.mermaid_validator import renderer
from mahavishnu.tools.mermaid_validator.renderer import (
    MermaidToolchainUnavailableError,
    extract_mermaid_blocks,
    find_broken_mermaid_blocks,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED = "required"
OPTIONAL = "optional"

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_FALSY = frozenset({"0", "false", "no", "off"})


def _repo_policy() -> str:
    """The guard policy declared by the repo, from pyproject.toml.

    A missing or unrecognised policy is a configuration error rather than a
    silent opt-out: a repo that has not said whether the guard is required
    has not chosen to skip it.
    """
    pyproject = REPO_ROOT / "pyproject.toml"
    try:
        with pyproject.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        pytest.fail(f"could not read the mermaid guard policy from {pyproject}: {exc}")

    policy = data.get("tool", {}).get("mermaid_guard", {}).get("policy")
    if policy is None:
        pytest.fail(
            "no mermaid guard policy is configured: add "
            '[tool.mermaid_guard] policy = "required" or "optional" to pyproject.toml'
        )
    value = str(policy).strip().lower()
    if value not in (REQUIRED, OPTIONAL):
        pytest.fail(
            f"invalid mermaid guard policy {policy!r}: expected "
            f"{REQUIRED!r} or {OPTIONAL!r}"
        )
    return value


def _env_tightens_policy() -> bool:
    """Whether the environment asks for the guard to be required.

    This can only tighten the repo's policy. An unrecognised value is a
    configuration error, so a typo cannot silently disable the guard.
    """
    raw = os.environ.get("MAHAVISHNU_REQUIRE_MERMAID")
    if raw is None:
        return False
    value = raw.strip().lower()
    if value in _TRUTHY:
        return True
    if value in _FALSY:
        return False
    pytest.fail(
        f"invalid MAHAVISHNU_REQUIRE_MERMAID={raw!r}: expected one of "
        f"{sorted(_TRUTHY | _FALSY)}"
    )


def _effective_policy() -> str:
    """The policy in force: the repo's, tightened by the environment."""
    policy = _repo_policy()
    if _env_tightens_policy():
        return REQUIRED
    return policy


def _run_mermaid_guard(root: Path, policy: str) -> None:
    """Fail on a broken diagram; skip when the toolchain is absent.

    Args:
        root: Directory to scan for markdown files.
        policy: ``required`` to fail when the toolchain is missing,
            ``optional`` to skip.
    """
    try:
        errors = find_broken_mermaid_blocks(root=root)
    except MermaidToolchainUnavailableError as exc:
        if policy == REQUIRED:
            pytest.fail(f"mermaid validator required but unavailable: {exc}")
        pytest.skip(f"mermaid validator unavailable: {exc}")
    if errors:
        formatted = "\n".join(f"  {e.relpath}:{e.line}  {e.error}" for e in errors)
        pytest.fail(f"{len(errors)} broken mermaid block(s):\n{formatted}")


def test_all_mermaid_blocks_parse() -> None:
    """Every fenced ```mermaid block in the repo must parse via mermaid.parse()."""
    _run_mermaid_guard(REPO_ROOT, _effective_policy())


def test_extract_mermaid_blocks_finds_expected_count() -> None:
    """Sanity check: the extractor should find at least one block in the repo.

    The docs/ directory has dozens of fenced mermaid blocks after wave-8.
    If this fails, the extractor is silently broken (e.g., regex changed).
    """
    blocks = extract_mermaid_blocks(
        REPO_ROOT / "docs" / "architecture" / "MEMORY_ARCHITECTURE.md"
    )
    assert len(blocks) >= 1, (
        "expected at least one mermaid block in MEMORY_ARCHITECTURE.md"
    )


class TestToolchainUnavailable:
    """An absent toolchain is an environment condition, not a broken diagram."""

    def _block(self) -> renderer.MermaidBlock:
        return renderer.MermaidBlock(
            file=Path("doc.md"), line=1, code="graph TD; A-->B"
        )

    def test_missing_jsdom_is_toolchain_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(renderer, "_locate_jsdom", lambda: None)
        with pytest.raises(MermaidToolchainUnavailableError, match="jsdom"):
            renderer.validate_mermaid_blocks([self._block()])

    def test_missing_mermaid_core_is_toolchain_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(renderer, "_locate_mermaid_core", lambda: None)
        with pytest.raises(MermaidToolchainUnavailableError, match="mermaid"):
            renderer.validate_mermaid_blocks([self._block()])

    def test_missing_node_is_toolchain_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(renderer, "_locate_mermaid_core", lambda: Path("core.mjs"))
        monkeypatch.setattr(renderer, "_locate_jsdom", lambda: Path("api.js"))

        def _no_node(*args, **kwargs):
            raise FileNotFoundError("node")

        monkeypatch.setattr(subprocess, "run", _no_node)
        with pytest.raises(
            MermaidToolchainUnavailableError, match="node is not on PATH"
        ):
            renderer.validate_mermaid_blocks([self._block()])

    def test_guard_skips_when_the_policy_is_optional(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _unavailable(root=None, paths=None):
            raise MermaidToolchainUnavailableError("jsdom not found")

        monkeypatch.setattr(
            sys.modules[__name__], "find_broken_mermaid_blocks", _unavailable
        )
        with pytest.raises(pytest.skip.Exception):
            _run_mermaid_guard(REPO_ROOT, OPTIONAL)

    def test_guard_fails_when_the_policy_is_required(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _unavailable(root=None, paths=None):
            raise MermaidToolchainUnavailableError("jsdom not found")

        monkeypatch.setattr(
            sys.modules[__name__], "find_broken_mermaid_blocks", _unavailable
        )
        with pytest.raises(pytest.fail.Exception):
            _run_mermaid_guard(REPO_ROOT, REQUIRED)

    def test_guard_still_fails_on_a_broken_diagram(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _broken(root=None, paths=None):
            return [
                renderer.MermaidValidationError(
                    file=Path("doc.md"), line=3, error="parse error"
                )
            ]

        monkeypatch.setattr(
            sys.modules[__name__], "find_broken_mermaid_blocks", _broken
        )
        for policy in (OPTIONAL, REQUIRED):
            with pytest.raises(pytest.fail.Exception):
                _run_mermaid_guard(REPO_ROOT, policy)


class TestGuardPolicy:
    """The policy is owned by the repo; the environment can only tighten it."""

    def test_repo_declares_a_valid_policy(self) -> None:
        assert _repo_policy() in (REQUIRED, OPTIONAL)

    def test_environment_can_tighten_the_policy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAHAVISHNU_REQUIRE_MERMAID", "1")
        assert _effective_policy() == REQUIRED

    def test_environment_cannot_loosen_a_required_policy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAHAVISHNU_REQUIRE_MERMAID", "0")
        monkeypatch.setattr(sys.modules[__name__], "_repo_policy", lambda: REQUIRED)
        assert _effective_policy() == REQUIRED

    def test_unrecognised_environment_value_is_a_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAHAVISHNU_REQUIRE_MERMAID", "treu")
        with pytest.raises(pytest.fail.Exception, match="MAHAVISHNU_REQUIRE_MERMAID"):
            _effective_policy()

    def test_missing_repo_policy_is_a_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            sys.modules[__name__], "REPO_ROOT", Path("/nonexistent-repo-root")
        )
        with pytest.raises(pytest.fail.Exception, match="policy"):
            _repo_policy()
