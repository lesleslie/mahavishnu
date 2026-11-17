from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from rich.console import Console

console = Console()


class MermaidToolchainUnavailableError(RuntimeError):
    """The mermaid toolchain is not installed, so no diagram can be checked.

    Raised when mermaid-cli, jsdom, or node itself cannot be found. This is
    an environment condition, not a validation failure: the caller could not
    check the diagrams at all. It is deliberately distinct from the plain
    RuntimeError raised when the validator runs and fails, which is a real
    problem with the diagrams or the validator itself.
    """


# Match a fenced ```mermaid block. Captures the body.
MERMAID_FENCE_RE = re.compile(
    r"^```mermaid\b[^\n]*\n(.*?)^```\s*$",
    re.MULTILINE | re.DOTALL,
)


@dataclass(frozen=True)
class MermaidBlock:
    """A fenced mermaid block found in a `.md` file."""

    file: Path
    line: int
    code: str


@dataclass(frozen=True)
class MermaidValidationError:
    """A mermaid block that failed to parse."""

    file: Path
    line: int
    error: str

    @property
    def relpath(self) -> str:
        try:
            return str(self.file.resolve().relative_to(Path.cwd().resolve()))
        except ValueError:
            return str(self.file)


# Paths we skip when scanning. The .venv/.git/etc. defaults are honored by
# `iter_markdown_files`; the docs extras are about ignoring generated /
# vendored material that doesn't ship with the project.
DEFAULT_SKIP_DIRS = (
    ".venv",
    "venv",
    "env",
    ".git",
    "node_modules",
    "dist",
    "build",
    ".egg-info",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".worktrees",
    ".claude",
    ".crackerjack",
    "uv",
)


def iter_markdown_files(
    root: Path,
    skip_dirs: tuple[str, ...] = DEFAULT_SKIP_DIRS,
) -> list[Path]:
    """Return all `.md` files under `root`, skipping default noisiness."""
    root = root.resolve()
    out: list[Path] = []
    for path in root.rglob("*.md"):
        if any(part in skip_dirs for part in path.parts):
            continue
        out.append(path)
    return out


def extract_mermaid_blocks(path: Path) -> list[MermaidBlock]:
    """Parse a `.md` file and return every fenced ```mermaid block."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return []
    blocks: list[MermaidBlock] = []
    for match in MERMAID_FENCE_RE.finditer(text):
        start = match.start()
        # Line numbers are 1-indexed for human display.
        line = text.count("\n", 0, start) + 1
        blocks.append(MermaidBlock(file=path, line=line, code=match.group(1)))
    return blocks


# Allow-listed prefixes for the mermaid-cli install. The validator trusts
# only paths that resolve under one of these. This prevents an attacker
# from planting a directory tree on PATH and having it picked up by a
# parent-walk — the walker must still land in a trusted prefix.
DEFAULT_MERMAID_PREFIXES: tuple[str, ...] = (
    "/usr/local/Cellar/mermaid-cli/",
    "/opt/homebrew/Cellar/mermaid-cli/",
    "/usr/local/lib/node_modules/",
    "/opt/homebrew/lib/node_modules/",
)

# The jsdom install this guard is allowed to execute. Like mermaid, jsdom
# is dynamically imported and run as code, so it has to be the package the
# reviewed lockfile pins -- not a global install, and not a copy somebody
# dropped into node_modules by hand.
#
# npm records the integrity hash of every package it installed in
# `node_modules/.package-lock.json`. Comparing that hash with the one in
# the checkout's `package-lock.json` proves the installed tree came from
# the tarball the lockfile pins, because npm verified that hash at install
# time. A global install leaves no such record, so it cannot be verified
# and is not accepted.
JSDOM_PACKAGE_DIR = "node_modules/jsdom"
JSDOM_ENTRYPOINT = "lib/api.js"


def _locate_mermaid_core() -> Path | None:
    """Return the absolute path to `mermaid/dist/mermaid.core.mjs`, if reachable.

    Resolution order (fail-closed; returns None if no trusted path):

    1. ``MAHAVISHNU_MERMAID_CORE`` env var (operator-pinned). Must pass
       the allow-list check.
    2. ``mmdc`` symlink resolution, validated against the allow-list.

    The Node.js runner takes the resolved path as argv[2] and uses dynamic
    ``import()`` to load it (Node ESM does NOT honor NODE_PATH for static
    imports in v18+). The path is then executed as code, so it must
    resolve to a verified, allow-listed install.
    """
    # 1. Explicit env var override (preferred for CI / production).
    env_override = os.environ.get("MAHAVISHNU_MERMAID_CORE")
    if env_override:
        path = Path(env_override).resolve()
        if _is_trusted_mermaid_path(path):
            return path
        raise RuntimeError(
            f"MAHAVISHNU_MERMAID_CORE={env_override} is not under a "
            f"trusted mermaid-cli prefix; refusing to import. Allowed "
            f"prefixes: {DEFAULT_MERMAID_PREFIXES}"
        )

    # 2. Walk from `mmdc` on PATH, but only return matches inside the
    # allow-list. This prevents an attacker who plants a directory on
    # PATH from having the walker resolve to a malicious install.
    bin_path = shutil.which("mmdc")
    if not bin_path:
        return None
    real = Path(bin_path).resolve()
    if not _is_trusted_mermaid_path(real):
        return None
    for candidate in real.parents:
        nm = candidate / "node_modules"
        if not (nm.is_dir() and (nm / "@mermaid-js" / "mermaid-cli").is_dir()):
            continue
        core = (
            nm
            / "@mermaid-js"
            / "mermaid-cli"
            / "node_modules"
            / "mermaid"
            / "dist"
            / "mermaid.core.mjs"
        )
        if core.is_file() and _is_trusted_mermaid_path(core):
            return core
    return None


def _checkout_root(start: Path) -> Path | None:
    """The nearest ancestor directory holding a ``package-lock.json``.

    The lockfile is the marker. It is the reviewed, git-tracked file that
    pins the Node packages, so an install sitting beside it can be checked
    against it.

    Args:
        start: A path inside the checkout to search upwards from.

    Returns:
        The checkout root, or ``None`` when no lockfile is found.
    """
    for candidate in (start, *start.parents):
        if (candidate / "package-lock.json").is_file():
            return candidate
    return None


def _jsdom_lock_entry(lockfile: Path) -> tuple[str, str] | None:
    """The (version, integrity) a lockfile pins for jsdom, if it pins one.

    Args:
        lockfile: Path to a ``package-lock.json``.

    Returns:
        The pinned version and integrity, or ``None`` when the lockfile
        does not pin jsdom or cannot be read.
    """
    try:
        with lockfile.open("rb") as handle:
            data = json.loads(handle.read())
    except OSError, ValueError:
        return None
    entry = data.get("packages", {}).get("node_modules/jsdom", {})
    version = entry.get("version")
    integrity = entry.get("integrity")
    if not version or not integrity:
        return None
    return str(version), str(integrity)


def _require_lockfile_pinned(checkout: Path) -> None:
    """Refuse an installed jsdom that the reviewed lockfile does not pin.

    jsdom is imported and executed as code by the Node runner, so the only
    acceptable copy is the one npm installed from the tarball the lockfile
    pins.

    Args:
        checkout: The checkout whose ``node_modules`` holds the install.

    Raises:
        MermaidToolchainUnavailableError: The installed tree does not
            match the lockfile, so it must not be executed.
    """
    expected = _jsdom_lock_entry(checkout / "package-lock.json")
    if expected is None:
        raise MermaidToolchainUnavailableError(
            f"{checkout}/package-lock.json does not pin jsdom, so an "
            "installed jsdom cannot be verified against it"
        )
    version, _integrity = expected
    installed = _jsdom_lock_entry(checkout / "node_modules" / ".package-lock.json")
    if installed is None:
        raise MermaidToolchainUnavailableError(
            f"{checkout}/node_modules carries no npm install record, so the "
            "installed jsdom cannot be verified; run `npm ci --ignore-scripts`"
        )
    if installed != expected:
        raise MermaidToolchainUnavailableError(
            f"the installed jsdom ({installed[0]}) is not the one the lockfile "
            f"pins ({version}); run `npm ci --ignore-scripts` in {checkout} to "
            "install the reviewed tree"
        )


def _locate_jsdom() -> Path | None:
    """Return the absolute path to the lockfile-pinned jsdom package.

    Resolution order:

    1. ``MAHAVISHNU_JSDOM`` -- an explicit operator pin. It is verified against
       the lockfile beside the install it names, so it can point at another
       checkout but never at an unverified package.
    2. ``<checkout>/node_modules/jsdom/`` -- the tree npm installed from
       the reviewed ``package-lock.json``.

    Returns:
        The path to ``jsdom/lib/api.js``, which exposes the ``JSDOM``
        class, or ``None`` when no lockfile-pinned install is present.

    Raises:
        MermaidToolchainUnavailableError: An install was found but does
            not match the lockfile, so it must not be executed.
    """
    env_override = os.environ.get("MAHAVISHNU_JSDOM")
    if env_override:
        path = Path(env_override).resolve()
        if not path.is_file():
            raise RuntimeError(
                f"MAHAVISHNU_JSDOM={env_override} does not exist or is not a file"
            )
        checkout = _checkout_root(path)
        if checkout is None:
            raise MermaidToolchainUnavailableError(
                f"MAHAVISHNU_JSDOM={env_override} is not inside a checkout with a "
                "package-lock.json, so the jsdom it names cannot be verified"
            )
        _require_lockfile_pinned(checkout)
        return path

    checkout = _checkout_root(Path(__file__).resolve())
    if checkout is None:
        return None
    package_dir = checkout / JSDOM_PACKAGE_DIR
    entry = package_dir / JSDOM_ENTRYPOINT
    if not entry.is_file():
        return None
    if package_dir.is_symlink():
        raise MermaidToolchainUnavailableError(
            f"{package_dir} is a symlink; the guard only executes a "
            "lockfile-pinned, non-symlinked install"
        )
    _require_lockfile_pinned(checkout)
    return entry


def _is_trusted_mermaid_path(path: Path) -> bool:
    """Allow-list check: `path` must live under a known-good mermaid prefix."""
    resolved = str(path.resolve())
    return any(resolved.startswith(prefix) for prefix in DEFAULT_MERMAID_PREFIXES)


def validate_mermaid_blocks(
    blocks: list[MermaidBlock],
    timeout: float = 30.0,
) -> list[MermaidValidationError]:
    """Run mermaid.parse() on each block via Node.js subprocess.

    Returns a list of MermaidValidationError. Empty list means every block
    passed. The Node.js runner is `mahavishnu/tools/mermaid_validator/
    validate_mermaid.mjs`, which uses `mermaid.parse()` (lexer-only,
    no chrome needed).
    """
    if not blocks:
        return []

    runner = Path(__file__).parent / "validate_mermaid.mjs"
    if not runner.exists():
        raise FileNotFoundError(f"validate_mermaid.mjs not found at {runner}")

    mermaid_core = _locate_mermaid_core()
    if not mermaid_core:
        raise MermaidToolchainUnavailableError(
            "could not find mermaid/dist/mermaid.core.mjs; install "
            "@mermaid-js/mermaid-cli (e.g. `brew install mermaid-cli`) "
            "or set a path that exposes mmdc on PATH"
        )

    jsdom = _locate_jsdom()
    if not jsdom:
        raise MermaidToolchainUnavailableError(
            "could not find the lockfile-pinned jsdom at "
            "node_modules/jsdom/lib/api.js; run `npm ci --ignore-scripts` in "
            "the mahavishnu repo to install the tree the reviewed package-lock.json "
            "pins, or set MAHAVISHNU_JSDOM to the path of an install that does "
            "match it"
        )

    payload = _build_payload(blocks)
    completed = _run_mermaid_subprocess(runner, mermaid_core, jsdom, payload, timeout)

    if completed.returncode != 0:
        raise RuntimeError(
            f"validate_mermaid.mjs exited {completed.returncode}: {completed.stderr.strip()[:500]}"
        )

    try:
        results = json.loads(completed.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"validate_mermaid.mjs returned invalid JSON: {e}; stdout={completed.stdout[:200]!r}"
        ) from e

    return _parse_results(results)


def _build_payload(blocks: list[MermaidBlock]) -> str:
    """Serialize the blocks into the JSON shape the Node runner expects."""
    return json.dumps(
        [{"file": str(b.file), "line": b.line, "code": b.code} for b in blocks]
    )


def _run_mermaid_subprocess(
    runner: Path,
    mermaid_core: Path,
    jsdom: Path,
    payload: str,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    """Invoke the Node validator, translating subprocess errors into RuntimeError."""
    try:
        return subprocess.run(
            ["node", str(runner), str(mermaid_core), str(jsdom)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as e:
        raise MermaidToolchainUnavailableError(
            "node is not on PATH; install Node.js to run the mermaid CI guard"
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"validate_mermaid.mjs timed out after {timeout}s on {len(payload)} bytes"
        ) from e


def _parse_results(
    results: list[dict[str, Any]],
) -> list[MermaidValidationError]:
    """Filter the runner output down to entries that flagged an error."""
    return [
        MermaidValidationError(
            file=Path(entry["file"]),
            line=entry["line"],
            error=entry.get("error", "<unknown error>"),
        )
        for entry in results
        if entry.get("status") == "error"
    ]


def find_broken_mermaid_blocks(
    root: Path | None = None,
    paths: list[Path] | None = None,
) -> list[MermaidValidationError]:
    """Top-level entry point: scan `.md` files and return parse failures.

    Pass either `root` (scan recursively) or `paths` (defaults to Path.cwd()).
    """
    if paths is None:
        if root is None:
            root = Path.cwd()
        paths = iter_markdown_files(root)
    all_blocks: list[MermaidBlock] = []
    for path in paths:
        all_blocks.extend(extract_mermaid_blocks(path))
    return validate_mermaid_blocks(all_blocks)


def print_errors(errors: list[MermaidValidationError]) -> None:
    """Pretty-print the broken blocks for the mahavishnu mermaid CLI."""
    if not errors:
        console.print("[green]✓ All mermaid blocks parse cleanly.[/green]")
        return
    console.print(f"[red]✗ {len(errors)} broken mermaid block(s):[/red]")
    for err in errors:
        console.print(f"  [red]{err.relpath}:{err.line}[/red]  {err.error}")
