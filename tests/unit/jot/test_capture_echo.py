from __future__ import annotations

from mahavishnu.jot.capture_echo import format_echo


def test_format_echo_simple() -> None:
    """Format: 'jot <short_id> captured (<wc> words, <cc> chars)'."""
    result = format_echo("a3f9c2b1e8d74f6a9c1b2e3f4a5b6c7d", "hello world")
    assert result == "jot a3f9c2 captured (2 words, 11 chars)"


def test_format_echo_single_word() -> None:
    result = format_echo("abcdef0123456789" * 2, "test")
    assert result == "jot abcdef captured (1 words, 4 chars)"


def test_format_echo_empty_text() -> None:
    result = format_echo("0000000000000000" * 2, "")
    assert result == "jot 000000 captured (0 words, 0 chars)"


def test_format_echo_uses_short_id_first_6() -> None:
    """Only the first 6 chars of the event ID appear in the echo."""
    event_id = "fedcba9876543210fedcba9876543210"
    result = format_echo(event_id, "test")
    assert "fedcba" in result
    assert "fedcba9876543210" not in result


def test_format_echo_word_count_uses_split() -> None:
    """Word count uses str.split() — multiple spaces collapse."""
    result = format_echo("a3f9c2b1e8d74f6a9c1b2e3f4a5b6c7d", "  hello   world  ")
    assert "2 words" in result
    # "  hello   world  " = 2 + 5 + 3 + 5 + 2 = 17 chars
    assert "17 chars" in result


def test_format_echo_unicode_chars() -> None:
    """Unicode characters count as single chars via len()."""
    result = format_echo("a3f9c2b1e8d74f6a9c1b2e3f4a5b6c7d", "héllo")
    assert "1 words" in result
    assert "5 chars" in result


def test_format_echo_no_trailing_newline() -> None:
    """format_echo must not add a trailing newline (print() does that)."""
    result = format_echo("a" * 32, "test")
    assert not result.endswith("\n")
