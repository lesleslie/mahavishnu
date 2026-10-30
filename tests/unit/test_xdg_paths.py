"""Guard tests for the XDG base-directory resolver.

Two guarantees are pinned here:

1. No Python file under the package (or the repo's ``scripts/`` directory)
   hardcodes the legacy ``~/.claude/data`` location. Comments and
   docstrings may still *name* the legacy path for historical context --
   only executable code is checked.
2. The resolver honours ``$XDG_DATA_HOME``, ``$XDG_STATE_HOME``,
   ``$XDG_CACHE_HOME`` and ``$XDG_CONFIG_HOME``.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import itertools
from pathlib import Path
import tokenize
from typing import TYPE_CHECKING

import pytest

from mahavishnu.core import xdg_paths
from mahavishnu.core.xdg_paths import cache_dir, config_dir, data_dir, state_dir

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = (REPO_ROOT / "mahavishnu", REPO_ROOT / "scripts")
LEGACY_FRAGMENT = ".claude/data"
LEGACY_SEGMENTS = (".claude", "data")


# ---------------------------------------------------------------------------
# Legacy-path guard
# ---------------------------------------------------------------------------


def _python_files() -> Iterator[Path]:
    """Yield every ``.py`` file under the scanned roots."""
    for root in SCAN_ROOTS:
        yield from sorted(root.rglob("*.py"))


def _strip_comments(source: str) -> str:
    """Return ``source`` with every COMMENT token removed."""
    tokens = [
        token
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type != tokenize.COMMENT
    ]
    return tokenize.untokenize(tokens)


def _strip_docstrings(source: str) -> str:
    """Return ``source`` with every docstring replaced by an empty literal.

    Rewriting the AST (rather than slicing the text) keeps the result
    valid Python: a function whose body is only a docstring still has a
    body, and triple-quoted docstrings keep their delimiters.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        body = node.body
        if not body:
            continue
        first = body[0]
        if not isinstance(first, ast.Expr):
            continue
        value = first.value
        is_text = isinstance(value, ast.Constant) and isinstance(value.value, str)
        if is_text or isinstance(value, ast.JoinedStr):
            body[0] = ast.Expr(value=ast.Constant(value=""))
    return ast.unparse(tree)


def _strip_comments_and_docstrings(source: str) -> str:
    """Return ``source`` without comments and without docstrings."""
    return _strip_docstrings(_strip_comments(source))


def _joined_path_literals(node: ast.AST) -> list[str]:
    """Return the string literals of every ``/``-joined path expression.

    ``Path.home() / ".claude" / "data"`` holds the legacy location without
    the literal substring ``".claude/data"`` appearing anywhere, so a plain
    substring check cannot see it. Re-joining the literals of each
    division chain recovers the path the code actually builds.
    """
    joined: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.BinOp) or not isinstance(child.op, ast.Div):
            continue
        parts = [
            part
            for part in ast.walk(child)
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        ]
        # ``ast.walk`` does not visit in source order, so sort by position
        # before joining or the path segments come out shuffled.
        parts.sort(key=lambda part: (part.lineno or 0, part.col_offset or 0))
        if parts:
            joined.append("/".join(part.value for part in parts))
    return joined


def _is_legacy_path(text: str) -> bool:
    """True when ``text`` names the legacy ``.claude``/``data`` pair.

    Compared segment by segment so that a sibling such as
    ``.claude/database`` is not mistaken for the legacy location.
    """
    segments = text.split("/")
    return any(
        first == LEGACY_SEGMENTS[0] and second == LEGACY_SEGMENTS[1]
        for first, second in itertools.pairwise(segments)
    )


@pytest.mark.parametrize("path", list(_python_files()), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_hardcoded_legacy_data_path(path: Path) -> None:
    """Code may not reintroduce the legacy ``~/.claude/data`` location."""
    source = path.read_text(encoding="utf-8")
    stripped = _strip_comments_and_docstrings(source)

    assert LEGACY_FRAGMENT not in stripped, f"{path} hardcodes the legacy data path"

    tree = ast.parse(stripped)
    for joined in _joined_path_literals(tree):
        assert not _is_legacy_path(joined), f"{path} hardcodes the legacy data path"


# ---------------------------------------------------------------------------
# Resolver behaviour
# ---------------------------------------------------------------------------


def test_data_dir_honours_xdg_data_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg-data")
    assert data_dir("session-buddy") == Path("/tmp/xdg-data/session-buddy")
    assert data_dir("mahavishnu") == Path("/tmp/xdg-data/mahavishnu")


def test_state_dir_honours_xdg_state_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", "/tmp/xdg-state")
    assert state_dir("mahavishnu") == Path("/tmp/xdg-state/mahavishnu")


def test_cache_dir_honours_xdg_cache_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/xdg-cache")
    assert cache_dir("session-buddy") == Path("/tmp/xdg-cache/session-buddy")


def test_config_dir_honours_xdg_config_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg-config")
    assert config_dir("session-buddy") == Path("/tmp/xdg-config/session-buddy")


def test_resolvers_fall_back_to_xdg_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no XDG variable set, the spec defaults under ``$HOME`` apply."""
    for variable in (
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("HOME", "/tmp/fake-home")

    assert data_dir() == Path("/tmp/fake-home/.local/share/session-buddy")
    assert state_dir() == Path("/tmp/fake-home/.local/state/session-buddy")
    assert cache_dir() == Path("/tmp/fake-home/.cache/session-buddy")
    assert config_dir() == Path("/tmp/fake-home/.config/session-buddy")


def test_empty_xdg_variable_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The XDG spec treats an empty variable the same as an unset one."""
    monkeypatch.setenv("XDG_DATA_HOME", "")
    monkeypatch.setenv("HOME", "/tmp/fake-home")
    assert data_dir() == Path("/tmp/fake-home/.local/share/session-buddy")


def test_default_app_name_is_session_buddy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default owner is Session-Buddy, never the consuming repo."""
    monkeypatch.setenv("XDG_DATA_HOME", "/tmp/xdg-data")
    assert data_dir() == Path("/tmp/xdg-data/session-buddy")
    assert data_dir().name == "session-buddy"


def _load_fresh_module() -> ModuleType:
    """Import a private copy of the resolver without touching global state."""
    module_path = Path(xdg_paths.__file__)
    spec = importlib.util.spec_from_file_location("xdg_paths_fresh", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_has_no_filesystem_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing the resolver must not create directories or write files."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    module = _load_fresh_module()

    assert module.data_dir("session-buddy") == tmp_path / "data" / "session-buddy"
    assert list(tmp_path.iterdir()) == []
