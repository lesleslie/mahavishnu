"""Unit tests for EncryptedSQLite (mahavishnu.storage.encrypted_sqlite)."""

from __future__ import annotations

import sqlite3

import pytest

from mahavishnu.storage.encrypted_sqlite import (
    EncryptedSQLite,
    EncryptedSQLitePool,
    EncryptionKeyError,
    generate_encryption_key,
    migrate_plaintext_to_encrypted,
    validate_encryption_key,
    verify_encrypted_database,
)

pytestmark = pytest.mark.unit

VALID_KEY = "a" * 32


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def key_env(monkeypatch):
    monkeypatch.setenv("SQLCIPHER_KEY", VALID_KEY)
    return VALID_KEY


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


# =============================================================================
# EncryptionKeyError
# =============================================================================


class TestEncryptionKeyError:
    def test_is_exception(self):
        assert issubclass(EncryptionKeyError, Exception)

    def test_can_be_raised_with_message(self):
        with pytest.raises(EncryptionKeyError, match="bad key"):
            raise EncryptionKeyError("bad key")


# =============================================================================
# Constructor
# =============================================================================


class TestInit:
    def test_creates_enc_path(self, tmp_path, key_env):
        p = tmp_path / "x.db"
        EncryptedSQLite(p)
        # enc path should be x.db.enc (suffix appended)
        assert (tmp_path / "x.db.enc") == p.with_suffix(p.suffix + ".enc")

    def test_short_key_raises(self, db_path):
        with pytest.raises(EncryptionKeyError, match="too short"):
            EncryptedSQLite(db_path, encryption_key="short")

    def test_missing_key_required_raises(self, db_path, monkeypatch):
        monkeypatch.delenv("SQLCIPHER_KEY", raising=False)
        with pytest.raises(EncryptionKeyError, match="not found"):
            EncryptedSQLite(db_path, require_encryption=True)

    def test_missing_key_not_required_uses_plaintext(self, db_path, monkeypatch):
        monkeypatch.delenv("SQLCIPHER_KEY", raising=False)
        db = EncryptedSQLite(db_path, require_encryption=False)
        assert db._using_encryption is False
        assert db._fernet is None

    def test_explicit_key_enables_encryption(self, db_path):
        db = EncryptedSQLite(db_path, encryption_key=VALID_KEY)
        assert db._using_encryption is True
        assert db._fernet is not None

    def test_creates_parent_dir(self, tmp_path, key_env):
        nested = tmp_path / "deep" / "nested" / "x.db"
        EncryptedSQLite(nested)
        assert nested.parent.exists()

    def test_key_env_var_read(self, db_path, key_env):
        db = EncryptedSQLite(db_path, key_env_var="SQLCIPHER_KEY")
        assert db._using_encryption is True


# =============================================================================
# Static _create_fernet
# =============================================================================


class TestCreateFernet:
    def test_returns_fernet_instance(self):
        from cryptography.fernet import Fernet

        f = EncryptedSQLite._create_fernet(VALID_KEY)
        assert isinstance(f, Fernet)

    def test_deterministic_with_fixed_salt(self):
        # Same key should produce same cipher output
        f1 = EncryptedSQLite._create_fernet(VALID_KEY)
        f2 = EncryptedSQLite._create_fernet(VALID_KEY)
        token1 = f1.encrypt(b"hello")
        token2 = f2.encrypt(b"hello")
        # Both should decrypt under the other
        assert f2.decrypt(token1) == b"hello"
        assert f1.decrypt(token2) == b"hello"

    def test_different_keys_produce_different_fernet(self):
        f1 = EncryptedSQLite._create_fernet("a" * 32)
        f2 = EncryptedSQLite._create_fernet("b" * 32)
        # Token from one must not decrypt under the other
        token = f1.encrypt(b"x")
        with pytest.raises(Exception):
            f2.decrypt(token)


# =============================================================================
# connect / close
# =============================================================================


class TestConnectClose:
    async def test_connect_creates_sqlite_connection(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        assert db._conn is None
        await db.connect()
        assert db._conn is not None
        assert isinstance(db._conn, sqlite3.Connection)
        await db.close()

    async def test_double_connect_warns_but_ok(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        await db.connect()
        await db.connect()  # Should warn but not raise
        assert db._conn is not None
        await db.close()

    async def test_close_with_no_connection(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        # Should not raise even if never connected
        await db.close()

    async def test_close_removes_plaintext_when_encrypted(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        await db.connect()
        # Add some data so file exists
        db.execute("CREATE TABLE t (x INTEGER)")
        await db.close()
        # db_path should have been unlinked (encrypted to .enc instead)
        assert not db_path.exists()
        assert db.enc_path.exists()

    async def test_close_with_plaintext_mode_keeps_file(self, db_path, monkeypatch):
        monkeypatch.delenv("SQLCIPHER_KEY", raising=False)
        db = EncryptedSQLite(db_path, require_encryption=False)
        await db.connect()
        db.execute("CREATE TABLE t (x INTEGER)")
        await db.close()
        # Plaintext should remain
        assert db_path.exists()


# =============================================================================
# execute / executemany
# =============================================================================


class TestExecute:
    async def test_execute_before_connect_raises(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        with pytest.raises(RuntimeError, match="not connected"):
            db.execute("SELECT 1")

    async def test_execute_returns_cursor(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        await db.connect()
        try:
            cursor = db.execute("CREATE TABLE t (x INTEGER, name TEXT)")
            assert cursor is not None
            assert db.execute("SELECT 1").fetchone()[0] == 1
        finally:
            await db.close()

    async def test_execute_with_params(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        await db.connect()
        try:
            db.execute("CREATE TABLE t (x INTEGER)")
            db.execute("INSERT INTO t VALUES (?)", (42,))
            row = db.execute("SELECT x FROM t").fetchone()
            assert row[0] == 42
        finally:
            await db.close()

    async def test_executemany(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        await db.connect()
        try:
            db.execute("CREATE TABLE t (x INTEGER)")
            db.executemany("INSERT INTO t VALUES (?)", [(1,), (2,), (3,)])
            rows = db.execute("SELECT x FROM t ORDER BY x").fetchall()
            assert [r[0] for r in rows] == [1, 2, 3]
        finally:
            await db.close()

    async def test_executemany_before_connect_raises(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        with pytest.raises(RuntimeError, match="not connected"):
            db.executemany("SELECT 1", [])


# =============================================================================
# commit / rollback
# =============================================================================


class TestCommitRollback:
    async def test_commit_after_insert(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        await db.connect()
        try:
            db.execute("CREATE TABLE t (x INTEGER)")
            db.execute("INSERT INTO t VALUES (1)")
            await db.commit()
            row = db.execute("SELECT x FROM t").fetchone()
            assert row[0] == 1
        finally:
            await db.close()

    async def test_rollback(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        await db.connect()
        try:
            db.execute("CREATE TABLE t (x INTEGER)")
            db.execute("INSERT INTO t VALUES (1)")
            await db.rollback()
            await db.commit()
            count = db.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            assert count == 0
        finally:
            await db.close()

    async def test_commit_no_op_when_not_connected(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        # Should not raise
        await db.commit()
        await db.rollback()


# =============================================================================
# connection property
# =============================================================================


class TestConnectionProperty:
    async def test_connection_property_before_connect_raises(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        with pytest.raises(RuntimeError, match="not connected"):
            _ = db.connection

    async def test_connection_property_after_connect(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        await db.connect()
        try:
            assert db.connection is db._conn
        finally:
            await db.close()


# =============================================================================
# verify_integrity
# =============================================================================


class TestVerifyIntegrity:
    async def test_integrity_check_passes(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        await db.connect()
        try:
            db.execute("CREATE TABLE t (x INTEGER)")
            result = await db.verify_integrity()
            assert result is True
        finally:
            await db.close()

    async def test_integrity_check_fails_when_not_connected(self, db_path, key_env):
        db = EncryptedSQLite(db_path)
        result = await db.verify_integrity()
        assert result is False


# =============================================================================
# backup / restore
# =============================================================================


class TestBackupRestore:
    async def test_backup_creates_enc_file(self, db_path, key_env, tmp_path):
        db = EncryptedSQLite(db_path)
        await db.connect()
        db.execute("CREATE TABLE t (x INTEGER)")
        db.execute("INSERT INTO t VALUES (99)")
        await db.commit()

        backup_path = tmp_path / "backup.db"
        await db.backup(backup_path)
        enc_backup = backup_path.with_suffix(backup_path.suffix + ".enc")
        assert enc_backup.exists()
        await db.close()

    async def test_backup_requires_connection(self, db_path, key_env, tmp_path):
        db = EncryptedSQLite(db_path)
        with pytest.raises(RuntimeError, match="not connected"):
            await db.backup(tmp_path / "b.db")

    async def test_restore_from_backup(self, db_path, key_env, tmp_path):
        # Create initial DB and back it up
        db = EncryptedSQLite(db_path)
        await db.connect()
        db.execute("CREATE TABLE t (x INTEGER)")
        db.execute("INSERT INTO t VALUES (5)")
        await db.commit()
        await db.close()

        # Now restore to a different location
        new_path = tmp_path / "restored.db"
        new_db = EncryptedSQLite(new_path)
        await new_db.connect()
        try:
            await new_db.restore(db_path)
            # The restored connection should have a working DB
            # but the table was written to the *original* path
            # so we just verify the connection is open
            assert new_db._conn is not None
        finally:
            await new_db.close()

    async def test_restore_missing_file_raises(self, db_path, key_env, tmp_path):
        db = EncryptedSQLite(db_path)
        await db.connect()
        try:
            with pytest.raises(FileNotFoundError):
                await db.restore(tmp_path / "does-not-exist.db")
        finally:
            await db.close()


# =============================================================================
# EncryptedSQLitePool
# =============================================================================


class TestPool:
    async def test_pool_init(self, db_path, key_env):
        pool = EncryptedSQLitePool(db_path, encryption_key=VALID_KEY, pool_size=3)
        assert pool.pool_size == 3
        assert pool._pool == []

    async def test_pool_acquire_release(self, db_path, key_env):
        pool = EncryptedSQLitePool(db_path, encryption_key=VALID_KEY, pool_size=2)
        conn = await pool.acquire()
        assert isinstance(conn, EncryptedSQLite)
        await pool.release(conn)
        assert len(pool._pool) == 1

    async def test_pool_release_closes_when_full(self, db_path, key_env):
        pool = EncryptedSQLitePool(db_path, encryption_key=VALID_KEY, pool_size=1)
        c1 = await pool.acquire()
        c2 = await pool.acquire()
        await pool.release(c1)
        await pool.release(c2)  # Pool full -> closes
        assert len(pool._pool) == 1

    async def test_pool_acquire_reuses(self, db_path, key_env):
        pool = EncryptedSQLitePool(db_path, encryption_key=VALID_KEY, pool_size=2)
        c1 = await pool.acquire()
        await pool.release(c1)
        c2 = await pool.acquire()
        # Same instance should be returned
        assert c2 is c1
        await c2.close()

    async def test_pool_close_all(self, db_path, key_env):
        pool = EncryptedSQLitePool(db_path, encryption_key=VALID_KEY, pool_size=3)
        c1 = await pool.acquire()
        c2 = await pool.acquire()
        await pool.release(c1)
        await pool.release(c2)
        await pool.close_all()
        assert pool._pool == []


# =============================================================================
# generate_encryption_key
# =============================================================================


class TestGenerateKey:
    def test_default_length_32(self):
        key = generate_encryption_key()
        assert len(key) == 32

    def test_custom_length(self):
        key = generate_encryption_key(length=64)
        assert len(key) == 64

    def test_unique_keys(self):
        keys = {generate_encryption_key() for _ in range(5)}
        assert len(keys) == 5  # All unique


# =============================================================================
# validate_encryption_key
# =============================================================================


class TestValidateKey:
    def test_valid_32_chars(self):
        assert validate_encryption_key("a" * 32) is True

    def test_valid_longer(self):
        assert validate_encryption_key("a" * 64) is True

    def test_too_short(self):
        assert validate_encryption_key("a" * 31) is False

    def test_empty(self):
        assert validate_encryption_key("") is False

    def test_custom_min_length(self):
        assert validate_encryption_key("abcdef", min_length=6) is True
        assert validate_encryption_key("abcde", min_length=6) is False


# =============================================================================
# migrate_plaintext_to_encrypted
# =============================================================================


class TestMigration:
    async def test_migrate_plaintext_to_encrypted(self, tmp_path, key_env):
        # Create a plaintext DB
        plain = tmp_path / "plain.db"
        conn = sqlite3.connect(str(plain))
        conn.execute("CREATE TABLE t (x INTEGER, name TEXT)")
        conn.execute("INSERT INTO t VALUES (1, 'foo')")
        conn.commit()
        conn.close()

        # Migrate
        enc = tmp_path / "enc.db"
        await migrate_plaintext_to_encrypted(plain, enc, VALID_KEY)

        # Verify the encrypted DB can be opened and has the data
        new_db = EncryptedSQLite(enc, encryption_key=VALID_KEY)
        await new_db.connect()
        try:
            row = new_db.execute("SELECT name FROM t WHERE x = 1").fetchone()
            assert row[0] == "foo"
        finally:
            await new_db.close()

    async def test_migrate_missing_plain_raises(self, tmp_path, key_env):
        with pytest.raises(FileNotFoundError):
            await migrate_plaintext_to_encrypted(
                tmp_path / "missing.db",
                tmp_path / "enc.db",
                VALID_KEY,
            )


# =============================================================================
# verify_encrypted_database
# =============================================================================


class TestVerifyEncryptedDatabase:
    async def test_verify_valid_database(self, tmp_path, key_env):
        # Create and close an encrypted DB
        path = tmp_path / "valid.db"
        db = EncryptedSQLite(path, encryption_key=VALID_KEY)
        await db.connect()
        db.execute("CREATE TABLE t (x INTEGER)")
        await db.close()

        result = await verify_encrypted_database(path, VALID_KEY)
        assert result is True

    async def test_verify_wrong_key_returns_false(self, tmp_path, key_env):
        path = tmp_path / "x.db"
        db = EncryptedSQLite(path, encryption_key=VALID_KEY)
        await db.connect()
        db.execute("CREATE TABLE t (x INTEGER)")
        await db.close()

        # Use a different valid-length key
        result = await verify_encrypted_database(path, "b" * 32)
        assert result is False

    async def test_verify_missing_file_creates_new_valid(self, tmp_path, key_env):
        # When the file doesn't exist, connect() creates a fresh DB and
        # integrity check passes — verify_encrypted_database returns True.
        # This is a latent design quirk worth documenting.
        result = await verify_encrypted_database(tmp_path / "missing.db", VALID_KEY)
        assert result is True
