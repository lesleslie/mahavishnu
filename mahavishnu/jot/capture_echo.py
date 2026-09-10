"""Capture echo formatter.

Produces the human-facing one-liner shown in stderr after a successful capture.
"""
from __future__ import annotations

from .short_id import short_id


def format_echo(event_id: str, text: str) -> str:
    """Format the capture echo: 'jot <short_id> captured (<wc> words, <cc> chars)'.

    Caller is responsible for printing to stderr with a trailing newline.
    """
    short = short_id(event_id)
    word_count = len(text.split())
    char_count = len(text)
    return f"jot {short} captured ({word_count} words, {char_count} chars)"
