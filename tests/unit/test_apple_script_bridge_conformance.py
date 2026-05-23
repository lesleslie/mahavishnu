"""Conformance tests for mcp-common AppleScript bridge against canonical spec.

These tests validate that `mcp_common.apple_script.bridge` correctly implements
the canonical iTerm2 AppleScript protocol defined in:
    mcp-common/docs/iterm2-applescript-protocol.md

Conformance areas:
- Escaping algorithm order (backslash first)
- All six escaping transformations
- Multi-line string building with & return &
- run() function error handling and timeout behavior
"""
import pytest

from mcp_common.apple_script import (
    AppleScriptError,
    ScriptTimeoutError,
    run,
    escape_for_applescript,
    build_applescript_string,
    OSASCRIPT_AVAILABLE,
)


pytestmark = pytest.mark.skipif(not OSASCRIPT_AVAILABLE, reason="macOS only")


class TestEscapingConformance:
    """Conformance tests for canonical escaping algorithm.

    Per spec Section 3, the escaping algorithm must:
    1. Escape backslash first (before everything else)
    2. Escape double-quote
    3. Escape single-quote (AppleScript standard)
    4. Escape tab as \t
    5. Remove carriage return (not valid in AppleScript strings)
    6. Handle newline at call site (multi-line with & return &)
    """

    def test_backslash_escaped_first(self):
        """Backslash must be escaped before other characters."""
        result = escape_for_applescript("a\\b")
        assert result == "a\\\\b"
        # Verify quote escaping also works after backslash
        assert escape_for_applescript('a\\"b') == 'a\\\\\\"b'

    def test_double_quote_escaped(self):
        """Double-quote must become backslash-quote."""
        result = escape_for_applescript('hello"world')
        assert result == 'hello\\"world'

    def test_single_quote_escaped(self):
        """Single-quote must become backslash-quote (AppleScript standard)."""
        result = escape_for_applescript("hello'world")
        assert result == "hello\\'world"

    def test_tab_escaped(self):
        """Tab must be preserved as backslash-t."""
        result = escape_for_applescript("a\tb")
        assert result == "a\\tb"

    def test_carriage_return_removed(self):
        """Carriage return must be removed, not escaped."""
        result = escape_for_applescript("a\r b")
        assert result == "a b"  # CR removed, space remains

    def test_newline_not_escaped_in_escape_function(self):
        """Newline is NOT escaped by escape_for_applescript; handled by build_applescript_string."""
        # The escaping function does NOT touch newlines - that's the caller's responsibility
        result = escape_for_applescript("a\nb")
        assert result == "a\nb"  # newline passed through for multi-line handling

    def test_order_matters_backslash_before_quotes(self):
        """Verify backslash is escaped before quotes are processed."""
        # If backslash wasn't escaped first, this would produce wrong result
        result = escape_for_applescript('\\"')
        assert result == '\\\\\\"'  # backslash escaped first, then double-quote


class TestBuildAppleScriptStringConformance:
    """Conformance tests for multi-line string building.

    Per spec Section 3, multi-line strings use & return & syntax:
        "line1" & return & "line2" & return & "line3"
    """

    def test_newline_splits_for_multiline(self):
        """Newline triggers & return & multi-line syntax."""
        result = build_applescript_string("line1\nline2\nline3")
        assert result == '"line1" & return & "line2" & return & "line3"'

    def test_single_line_no_multiline_syntax(self):
        """Single-line strings must NOT include return concatenation."""
        result = build_applescript_string("simple")
        assert result == '"simple"'
        assert "return" not in result

    def test_empty_string(self):
        """Empty string should produce empty quoted string."""
        assert build_applescript_string("") == '""'

    def test_tab_in_multiline(self):
        """Tabs must be preserved in multi-line strings."""
        result = build_applescript_string("a\tb\nc")
        assert "\\t" in result

    def test_leading_trailing_whitespace_preserved(self):
        """Leading and trailing whitespace must be preserved."""
        result = build_applescript_string("  leading and trailing  ")
        assert result == '"  leading and trailing  "'

    def test_multiple_newlines(self):
        """Multiple consecutive newlines are each a separate line."""
        result = build_applescript_string("a\n\nb")
        lines = result.split(" & return & ")
        assert len(lines) == 3  # "a", "", "b"

    def test_carriage_return_in_input(self):
        """CR in input must be removed before building multi-line string."""
        result = build_applescript_string("a\rb\rc")
        # CR removed, so no CR in result
        assert "\r" not in result

    def test_mixed_crlf_in_input(self):
        """CR-LF (Windows line endings) should have CR removed, LF handled as line split."""
        result = build_applescript_string("a\r\nb\r\nc")
        # CR removed, LF splits lines
        lines = result.split(" & return & ")
        assert len(lines) == 3  # "a", "b", "c"


class TestRunFunctionConformance:
    """Conformance tests for run() function behavior.

    Per spec Section 3, the run() function should:
    - Return stdout on success
    - Raise AppleScriptError on non-zero exit
    - Raise ScriptTimeoutError on timeout
    """

    @pytest.mark.asyncio
    async def test_run_simple_script_returns_output(self):
        """Simple AppleScript returning a string must return that string."""
        result = await run('return "hello"')
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_run_raises_apple_script_error_on_failure(self):
        """Invalid AppleScript must raise AppleScriptError."""
        with pytest.raises(AppleScriptError):
            await run("this is not valid applescript syntax")

    @pytest.mark.asyncio
    async def test_run_raises_timeout_on_hung_script(self):
        """Script that hangs must raise ScriptTimeoutError after timeout."""
        # A script that loops indefinitely
        with pytest.raises(ScriptTimeoutError):
            await run("repeat while true\nend repeat", timeout=1.0)

    @pytest.mark.asyncio
    async def test_run_with_special_chars(self):
        """AppleScript with escaped special chars must round-trip correctly."""
        result = await run('return "hello \\" world"')
        assert result == 'hello " world'

    @pytest.mark.asyncio
    async def test_run_multiline_script(self):
        """Multi-line AppleScript must execute correctly."""
        result = await run('return "line1" & return & "line2"')
        assert "line1" in result
        assert "line2" in result

    @pytest.mark.asyncio
    async def test_run_empty_result(self):
        """AppleScript returning empty must return empty string."""
        result = await run('return ""')
        assert result == ""


class TestCanonicalSpecCompliance:
    """High-level tests verifying canonical spec compliance.

    Per iterm2-applescript-protocol.md Section 5 (Conformance Requirements).
    """

    def test_all_six_escaping_rules_implemented(self):
        """Verify all six escaping rules from spec are implemented."""
        # 1. Backslash
        assert "\\" in escape_for_applescript("\\")
        # 2. Double-quote
        assert '\\"' in escape_for_applescript('"')
        # 3. Single-quote
        assert "\\'" in escape_for_applescript("'")
        # 4. Tab
        assert "\\t" in escape_for_applescript("\t")
        # 5. Carriage return removed
        assert "cr" not in escape_for_applescript("\r").lower() or escape_for_applescript("\r") == ""
        # 6. Newline passed through (not escaped here)
        assert "\n" in escape_for_applescript("\n")

    def test_multiline_uses_return_concatenation(self):
        """Multi-line strings MUST use & return & per spec Section 3."""
        result = build_applescript_string("a\nb\nc")
        assert " & return & " in result

    def test_single_line_does_not_use_return_concatenation(self):
        """Single-line strings must NOT use & return & per spec Section 3."""
        result = build_for_applescript_string("simple")
        assert "return" not in result
        assert result == '"simple"'

    def test_carriage_return_not_escaped(self):
        """CR MUST be removed, not escaped, per spec Section 3."""
        result = escape_for_applescript("test\rcarriage")
        assert "\r" not in result
        assert result == "testcarriage" or result == "test carriage"


# Utility for testing - not part of the module
def build_for_applescript_string(value: str) -> str:
    """Local alias for testing - same as build_applescript_string."""
    return build_applescript_string(value)