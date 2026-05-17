from __future__ import annotations

import pytest

from mahavishnu.core.repo_nicknames import get_repo_nicknames, normalize_nicknames


@pytest.mark.parametrize(
    ("nickname", "nicknames", "expected"),
    [
        ("  alpha  ", None, ["alpha"]),
        ("alpha", "beta", ["alpha", "beta"]),
        ("alpha", ["beta", "alpha", "gamma", "beta"], ["alpha", "beta", "gamma"]),
        (None, ("  beta  ", "", "gamma"), ["beta", "gamma"]),
        (None, None, []),
    ],
)
def test_normalize_nicknames_preserves_order_and_deduplicates(
    nickname: str | None,
    nicknames: str | list[str] | tuple[str, ...] | None,
    expected: list[str],
) -> None:
    assert normalize_nicknames(nickname=nickname, nicknames=nicknames) == expected


def test_get_repo_nicknames_reads_mapping_fields() -> None:
    repo = {
        "nickname": "delta",
        "nicknames": ["delta", "epsilon", "  zeta  "],
    }

    assert get_repo_nicknames(repo) == ["delta", "epsilon", "zeta"]
