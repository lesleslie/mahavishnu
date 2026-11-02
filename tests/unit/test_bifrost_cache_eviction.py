"""Unit tests for the Bifrost cache eviction sweep.

req: REQ-BIFROST-042, REQ-BIFROST-043

The sweep runs against the live Redis that also carries the event bus and
the Oneiric queue, so the tests pin three things: that expired entries go,
that nothing else does, and that the delete is atomic against a write that
lands between the scan and the delete.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mahavishnu.bifrost.cache_eviction import (
    CACHE_PREFIXES,
    DELETE_IF_EXPIRED_LUA,
    EXPIRES_FIELD,
    is_expired,
    parse_expiry,
    resolve_vector_store_addr,
    sweep_expired_entries,
)

if TYPE_CHECKING:
    from pathlib import Path

NOW = 1_700_000_000.0
EXPIRED_AT = str(int(NOW - 60)).encode()
LIVE_AT = str(int(NOW + 600)).encode()


class FakeRedis:
    """A Redis stand-in that mimics the parts of the server the sweep uses.

    ``eval`` re-reads the entry's ``expires_at`` at delete time, the way
    the Lua script does. That is what makes the atomicity testable: a test
    can rewrite an entry between the scan and the delete and assert that the
    rewrite survives.
    """

    def __init__(self, entries: dict[bytes, dict[bytes, bytes]]) -> None:
        self.entries = entries
        self.eval_calls: list[tuple[str, list[bytes], list[bytes]]] = []

    def scan_iter(self, match: str, count: int) -> Any:
        prefix = match.removesuffix("*")

        async def _iter() -> Any:
            for key in list(self.entries):
                if key.decode("utf-8", "replace").startswith(prefix):
                    yield key

        return _iter()

    async def hget(self, key: bytes, field: bytes) -> bytes | None:
        return self.entries.get(key, {}).get(field)

    async def eval(self, script: str, keys: list[bytes], args: list[bytes]) -> int:
        """Stand in for the server-side ``EVAL`` (Redis Lua), not Python's eval."""
        self.eval_calls.append((script, list(keys), list(args)))
        field = args[0].decode("utf-8")
        cutoff = float(args[1].decode("utf-8"))
        deleted = 0
        for key in keys:
            entry = self.entries.get(key)
            if entry is None:
                continue
            raw = entry.get(field.encode("utf-8"))
            if raw is None:
                continue
            try:
                expires_at = float(raw)
            except (TypeError, ValueError):
                continue
            if expires_at <= cutoff:
                del self.entries[key]
                deleted += 1
        return deleted


def _entry(expires_at: bytes | None) -> dict[bytes, bytes]:
    entry: dict[bytes, bytes] = {b"response": b"payload"}
    if expires_at is not None:
        entry[EXPIRES_FIELD.encode("utf-8")] = expires_at
    return entry


class TestParseExpiry:
    """The ``expires_at`` field is read as epoch seconds."""

    def test_reads_bytes(self) -> None:
        assert parse_expiry(b"1700000000") == 1_700_000_000.0

    def test_reads_str(self) -> None:
        assert parse_expiry("1700000000") == 1_700_000_000.0

    def test_missing_field_is_none(self) -> None:
        assert parse_expiry(None) is None

    def test_unparseable_is_none(self) -> None:
        assert parse_expiry(b"not-a-number") is None

    def test_non_utf8_bytes_are_none(self) -> None:
        assert parse_expiry(b"\xbb\xfe\x00") is None


class TestIsExpired:
    """Expiry is decided by the entry's own field, and only by it."""

    def test_past_expiry_is_expired(self) -> None:
        assert is_expired(EXPIRED_AT, NOW) is True

    def test_future_expiry_is_live(self) -> None:
        assert is_expired(LIVE_AT, NOW) is False

    def test_exactly_now_is_expired(self) -> None:
        assert is_expired(str(int(NOW)).encode(), NOW) is True

    def test_missing_field_is_not_expired(self) -> None:
        """Unknown state is kept -- deleting a live entry costs a miss."""
        assert is_expired(None, NOW) is False

    def test_unparseable_field_is_not_expired(self) -> None:
        assert is_expired(b"garbage", NOW) is False


class TestSweepExpiredEntries:
    """The sweep removes expired entries and nothing else."""

    async def test_removes_expired_and_keeps_live(self) -> None:
        client = FakeRedis(
            {
                b"BifrostSemanticCachePlugin:expired": _entry(EXPIRED_AT),
                b"BifrostSemanticCachePlugin:live": _entry(LIVE_AT),
            }
        )
        result = await sweep_expired_entries(client, now=NOW)  # type: ignore[arg-type]

        assert result.scanned == 2
        assert result.expired == 1
        assert result.live == 1
        assert result.deleted == 1
        assert b"BifrostSemanticCachePlugin:expired" not in client.entries
        assert b"BifrostSemanticCachePlugin:live" in client.entries

    async def test_keeps_entries_without_an_expiry(self) -> None:
        """An entry with no ``expires_at`` is never deleted."""
        client = FakeRedis({b"BifrostSemanticCachePlugin:unknown": _entry(None)})
        result = await sweep_expired_entries(client, now=NOW)  # type: ignore[arg-type]

        assert result.unknown_expiry == 1
        assert result.expired == 0
        assert result.deleted == 0
        assert b"BifrostSemanticCachePlugin:unknown" in client.entries

    async def test_does_not_touch_non_bifrost_keys(self) -> None:
        """The event bus and the Oneiric queue share this Redis."""
        client = FakeRedis(
            {
                b"bodai:events:e2e-abc": _entry(EXPIRED_AT),
                b"oneiric-queue": _entry(EXPIRED_AT),
            }
        )
        result = await sweep_expired_entries(client, now=NOW)  # type: ignore[arg-type]

        assert result.scanned == 0
        assert result.deleted == 0
        assert b"bodai:events:e2e-abc" in client.entries
        assert b"oneiric-queue" in client.entries

    async def test_dry_run_deletes_nothing(self) -> None:
        client = FakeRedis({b"BifrostSemanticCachePlugin:expired": _entry(EXPIRED_AT)})
        result = await sweep_expired_entries(client, now=NOW, dry_run=True)  # type: ignore[arg-type]

        assert result.expired == 1
        assert result.deleted == 0
        assert client.eval_calls == []
        assert b"BifrostSemanticCachePlugin:expired" in client.entries

    async def test_a_rewrite_between_scan_and_delete_survives(self) -> None:
        """The delete is atomic: a live entry rewritten mid-sweep survives."""
        client = FakeRedis({b"BifrostSemanticCachePlugin:entry": _entry(EXPIRED_AT)})
        original_hget = client.hget

        async def _hget(key: bytes, field: bytes) -> bytes | None:
            raw = await original_hget(key, field)
            # Simulate the gateway writing a fresh entry between the scan
            # and the delete.
            client.entries[key] = _entry(LIVE_AT)
            return raw

        client.hget = _hget  # type: ignore[method-assign]
        result = await sweep_expired_entries(client, now=NOW)  # type: ignore[arg-type]

        assert result.expired == 1
        assert result.deleted == 0
        assert b"BifrostSemanticCachePlugin:entry" in client.entries

    async def test_sweeps_every_declared_prefix(self) -> None:
        client = FakeRedis(
            {
                b"BifrostSemanticCachePlugin:a": _entry(EXPIRED_AT),
                b"BifrostSemanticCachePlugin_d1:b": _entry(EXPIRED_AT),
                b"BifrostLocalCachePlugin:c": _entry(EXPIRED_AT),
            }
        )
        result = await sweep_expired_entries(client, now=NOW)  # type: ignore[arg-type]

        assert result.scanned == 3
        assert result.deleted == 3
        assert client.entries == {}

    async def test_delete_uses_the_lua_script_with_the_cutoff(self) -> None:
        client = FakeRedis({b"BifrostSemanticCachePlugin:expired": _entry(EXPIRED_AT)})
        await sweep_expired_entries(client, now=NOW)  # type: ignore[arg-type]

        assert len(client.eval_calls) == 1
        script, keys, args = client.eval_calls[0]
        assert script == DELETE_IF_EXPIRED_LUA
        assert keys == [b"BifrostSemanticCachePlugin:expired"]
        assert args[0] == EXPIRES_FIELD.encode("utf-8")
        assert int(args[1]) == int(NOW)

    async def test_sweep_is_idempotent(self) -> None:
        client = FakeRedis({b"BifrostSemanticCachePlugin:expired": _entry(EXPIRED_AT)})
        first = await sweep_expired_entries(client, now=NOW)  # type: ignore[arg-type]
        second = await sweep_expired_entries(client, now=NOW)  # type: ignore[arg-type]

        assert first.deleted == 1
        assert second.deleted == 0
        assert second.scanned == 0

    async def test_a_read_failure_is_counted_and_does_not_abort(self) -> None:
        client = FakeRedis({b"BifrostSemanticCachePlugin:a": _entry(EXPIRED_AT)})

        async def _boom(key: bytes, field: bytes) -> bytes | None:
            raise OSError("connection reset")

        client.hget = _boom  # type: ignore[method-assign]
        result = await sweep_expired_entries(client, now=NOW)  # type: ignore[arg-type]

        assert result.errors == 1
        assert result.deleted == 0

    async def test_a_failed_delete_batch_is_counted(self) -> None:
        """A batch that cannot be deleted is reported, not silently dropped."""
        client = FakeRedis({b"BifrostSemanticCachePlugin:a": _entry(EXPIRED_AT)})

        async def _boom(script: str, keys: list[bytes], args: list[bytes]) -> int:
            raise OSError("connection reset")

        client.eval = _boom  # type: ignore[method-assign]
        result = await sweep_expired_entries(client, now=NOW)  # type: ignore[arg-type]

        assert result.expired == 1
        assert result.deleted == 0
        assert result.errors == 1


class TestResolveVectorStoreAddr:
    """The sweep targets the Redis the gateway's own config names."""

    def test_reads_the_address_from_the_config(self, tmp_path: Path) -> None:
        config = tmp_path / "config.json"
        config.write_text(
            '{"vector_store": {"type": "redis", "config": {"addr": "example.internal:6380"}}}',
            encoding="utf-8",
        )
        assert resolve_vector_store_addr(config) == ("example.internal", 6380)

    def test_missing_config_falls_back(self, tmp_path: Path) -> None:
        assert resolve_vector_store_addr(tmp_path / "absent.json") == ("localhost", 6379)

    def test_config_without_a_vector_store_falls_back(self, tmp_path: Path) -> None:
        config = tmp_path / "config.json"
        config.write_text('{"client": {}}', encoding="utf-8")
        assert resolve_vector_store_addr(config) == ("localhost", 6379)

    def test_malformed_config_falls_back(self, tmp_path: Path) -> None:
        config = tmp_path / "config.json"
        config.write_text("{not json", encoding="utf-8")
        assert resolve_vector_store_addr(config) == ("localhost", 6379)


@pytest.mark.parametrize("prefix", CACHE_PREFIXES)
def test_every_swept_prefix_is_namespaced(prefix: str) -> None:
    """A swept prefix must not be a bare namespace -- it needs the colon."""
    assert prefix.endswith(":")
    assert prefix.startswith("Bifrost")


class TestCacheSweepAgent:
    """The timer is the wiring -- without it the store grows unbounded."""

    def test_install_copies_the_plist_and_validates_it(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mahavishnu.bifrost import lifecycle

        source = tmp_path / "source.plist"
        source.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict><key>Label</key>'
            "<string>ai.bifrost.cache-sweep</string></dict></plist>\n",
            encoding="utf-8",
        )
        target = tmp_path / "LaunchAgents" / "ai.bifrost.cache-sweep.plist"
        monkeypatch.setattr(lifecycle, "SOURCE_CACHE_SWEEP_PLIST", source)
        monkeypatch.setattr(lifecycle, "TARGET_CACHE_SWEEP_PLIST", target)

        lifecycle.install_cache_sweep_plist()

        assert target.exists()
        assert "ai.bifrost.cache-sweep" in target.read_text(encoding="utf-8")

    def test_install_rejects_a_malformed_plist(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A plist launchd cannot parse must fail before it is installed."""
        from mahavishnu.bifrost import lifecycle

        source = tmp_path / "source.plist"
        source.write_text("not a plist", encoding="utf-8")
        target = tmp_path / "LaunchAgents" / "ai.bifrost.cache-sweep.plist"
        monkeypatch.setattr(lifecycle, "SOURCE_CACHE_SWEEP_PLIST", source)
        monkeypatch.setattr(lifecycle, "TARGET_CACHE_SWEEP_PLIST", target)

        with pytest.raises(Exception):
            lifecycle.install_cache_sweep_plist()

    def test_stop_removes_the_plist(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mahavishnu.bifrost import lifecycle

        target = tmp_path / "LaunchAgents" / "ai.bifrost.cache-sweep.plist"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("<plist/>", encoding="utf-8")
        monkeypatch.setattr(lifecycle, "TARGET_CACHE_SWEEP_PLIST", target)
        monkeypatch.setattr(lifecycle, "bootout_cache_sweep", lambda: None)

        lifecycle.stop_cache_sweep()

        assert not target.exists()

    def test_stop_is_safe_when_the_plist_is_absent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from mahavishnu.bifrost import lifecycle

        monkeypatch.setattr(
            lifecycle, "TARGET_CACHE_SWEEP_PLIST", tmp_path / "absent.plist"
        )
        monkeypatch.setattr(lifecycle, "bootout_cache_sweep", lambda: None)

        lifecycle.stop_cache_sweep()  # must not raise
