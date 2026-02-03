"""Integration tests for encrypted SQLite storage.

Tests the application-level encryption using cryptography.fernet
instead of SQLCipher's pysqlcipher3 (which has Python 3.13 compatibility issues).
"""

import asyncio
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from mahavishnu.storage.encrypted_sqlite import (
    EncryptedSQLite,
    EncryptedSQLitePool,
    EncryptionKeyError,
    generate_encryption_key,
    validate_encryption_key,
    migrate_plaintext_to_encrypted,
    verify_encrypted_database,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_dir():
    """Create temporary directory for test databases."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def encryption_key():
    """Generate encryption key for testing."""
    return "test_encryption_key_32_characters_long_"  # 42 chars, meets 32 minimum


@pytest.fixture
def plaintext_db(temp_dir):
    """Create plaintext SQLite database for migration tests."""
    db_path = temp_dir / "plaintext.db"

    # Create and populate database
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Create test table
    cursor.execute(
        """
        CREATE TABLE test_data (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            value INTEGER
        )
    """
    )

    # Insert test data
    cursor.execute("INSERT INTO test_data (name, value) VALUES (?, ?)", ("test1", 100))
    cursor.execute("INSERT INTO test_data (name, value) VALUES (?, ?)", ("test2", 200))

    conn.commit()
    conn.close()

    return db_path


# =============================================================================
# BASIC FUNCTIONALITY TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_encrypted_sqlite_basic_operations(temp_dir, encryption_key):
    """Test basic database operations with encryption."""
    db_path = temp_dir / "test.db"

    # Create encrypted database
    db = EncryptedSQLite(db_path, encryption_key=encryption_key)
    await db.connect()

    # Create table
    db.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT
        )
    """
    )
    await db.commit()

    # Insert data
    db.execute("INSERT INTO users (name, email) VALUES (?, ?)", ("Alice", "alice@example.com"))
    db.execute("INSERT INTO users (name, email) VALUES (?, ?)", ("Bob", "bob@example.com"))
    await db.commit()

    # Query data
    cursor = db.execute("SELECT * FROM users WHERE name = ?", ("Alice",))
    row = cursor.fetchone()

    assert row is not None
    assert row["name"] == "Alice"
    assert row["email"] == "alice@example.com"

    await db.close()

    # Verify encrypted file exists
    enc_path = db_path.with_suffix(db_path.suffix + ".enc")
    assert enc_path.exists(), f"Encrypted database file should exist at {enc_path}"

    # Verify plaintext database was removed after close
    assert not db_path.exists(), "Plaintext database should be removed after encryption"


@pytest.mark.asyncio
async def test_encrypted_sqlite_reopen_with_correct_key(temp_dir, encryption_key):
    """Test reopening encrypted database with correct key."""
    db_path = temp_dir / "test.db"

    # Create and populate database
    db1 = EncryptedSQLite(db_path, encryption_key=encryption_key)
    await db1.connect()

    db1.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
    db1.execute("INSERT INTO test (value) VALUES (?)", ("secret_data",))
    await db1.commit()
    await db1.close()

    # Reopen with same key
    db2 = EncryptedSQLite(db_path, encryption_key=encryption_key)
    await db2.connect()

    cursor = db2.execute("SELECT * FROM test")
    rows = cursor.fetchall()

    assert len(rows) == 1
    assert rows[0]["value"] == "secret_data"

    await db2.close()


@pytest.mark.asyncio
async def test_encrypted_sqlite_fail_with_wrong_key(temp_dir, encryption_key):
    """Test that wrong key fails to decrypt database."""
    db_path = temp_dir / "test.db"

    # Create database with key1
    db1 = EncryptedSQLite(db_path, encryption_key=encryption_key)
    await db1.connect()

    db1.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
    db1.execute("INSERT INTO test (value) VALUES (?)", ("secret_data",))
    await db1.commit()
    await db1.close()

    # Try to open with different key
    db2 = EncryptedSQLite(db_path, encryption_key="wrong_key_32_characters_long_____")

    with pytest.raises(EncryptionKeyError, match="Database decryption failed"):
        await db2.connect()


# =============================================================================
# KEY VALIDATION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_encryption_key_too_short(temp_dir):
    """Test that short keys are rejected."""
    db_path = temp_dir / "test.db"

    with pytest.raises(EncryptionKeyError, match="too short"):
        EncryptedSQLite(db_path, encryption_key="short")  # Only 5 chars


def test_generate_encryption_key():
    """Test encryption key generation."""
    key = generate_encryption_key()

    assert len(key) >= 32, "Generated key should be at least 32 characters"

    # Different calls generate different keys
    key2 = generate_encryption_key()
    assert key != key2, "Each call should generate unique key"


def test_validate_encryption_key():
    """Test encryption key validation."""
    # Valid keys
    assert validate_encryption_key("a" * 32) is True
    assert validate_encryption_key("a" * 100) is True

    # Invalid keys
    assert validate_encryption_key("short") is False
    assert validate_encryption_key("") is False


# =============================================================================
# PLAINTEXT FALLBACK TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_plaintext_fallback_when_no_key(temp_dir):
    """Test plaintext fallback when encryption not required."""
    db_path = temp_dir / "test.db"

    # Create database without encryption key (fallback mode)
    db = EncryptedSQLite(db_path, require_encryption=False)
    await db.connect()

    db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO test (value) VALUES (?)", ("plaintext_data",))
    await db.commit()
    await db.close()

    # Reopen without encryption key
    db2 = EncryptedSQLite(db_path, require_encryption=False)
    await db2.connect()

    cursor = db2.execute("SELECT * FROM test")
    rows = cursor.fetchall()

    assert len(rows) == 1
    assert rows[0]["value"] == "plaintext_data"

    await db2.close()


# =============================================================================
# BACKUP AND RESTORE TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_backup_and_restore(temp_dir, encryption_key):
    """Test encrypted backup and restore."""
    db_path = temp_dir / "test.db"
    backup_path = temp_dir / "backup.db"

    # Create database
    db = EncryptedSQLite(db_path, encryption_key=encryption_key)
    await db.connect()

    db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO test (value) VALUES (?)", ("important_data",))
    await db.commit()

    # Create backup
    await db.backup(backup_path)
    await db.close()

    # Verify backup exists (as .enc file)
    backup_enc_path = backup_path.with_suffix(backup_path.suffix + ".enc")
    assert backup_enc_path.exists(), "Encrypted backup should exist"

    # Restore backup to new location
    restore_path = temp_dir / "restored.db"
    db2 = EncryptedSQLite(restore_path, encryption_key=encryption_key)
    await db2.connect()

    # Restore from backup
    await db2.restore(backup_path)

    # Verify data
    cursor = db2.execute("SELECT * FROM test")
    rows = cursor.fetchall()

    assert len(rows) == 1
    assert rows[0]["value"] == "important_data"

    await db2.close()


# =============================================================================
# INTEGRITY CHECK TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_verify_integrity_success(temp_dir, encryption_key):
    """Test database integrity check for valid database."""
    db_path = temp_dir / "test.db"

    db = EncryptedSQLite(db_path, encryption_key=encryption_key)
    await db.connect()

    db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
    await db.commit()

    # Verify integrity
    is_valid = await db.verify_integrity()

    assert is_valid is True

    await db.close()


@pytest.mark.asyncio
async def test_verify_integrity_not_connected(temp_dir, encryption_key):
    """Test integrity check fails when not connected."""
    db_path = temp_dir / "test.db"

    db = EncryptedSQLite(db_path, encryption_key=encryption_key)

    # Not connected, should return False
    is_valid = await db.verify_integrity()

    assert is_valid is False


# =============================================================================
# CONNECTION POOL TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_connection_pool_acquire_release(temp_dir, encryption_key):
    """Test connection pool acquire and release."""
    db_path = temp_dir / "test.db"

    pool = EncryptedSQLitePool(db_path, encryption_key=encryption_key, pool_size=2)

    # Acquire first connection
    conn1 = await pool.acquire()
    assert conn1 is not None

    # Acquire second connection
    conn2 = await pool.acquire()
    assert conn2 is not None

    # Release first connection
    await pool.release(conn1)

    # Acquire again (should get released connection)
    conn3 = await pool.acquire()
    assert conn3 is not None

    await pool.close_all()


@pytest.mark.asyncio
async def test_connection_pool_max_size(temp_dir, encryption_key):
    """Test connection pool respects max size."""
    db_path = temp_dir / "test.db"

    pool = EncryptedSQLitePool(db_path, encryption_key=encryption_key, pool_size=2)

    # Acquire max connections
    conn1 = await pool.acquire()
    conn2 = await pool.acquire()

    # Release connection beyond pool size (should close, not pool)
    conn3 = await pool.acquire()
    await pool.release(conn3)  # Should close connection (pool full)

    await pool.close_all()


# =============================================================================
# MIGRATION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_migrate_plaintext_to_encrypted(plaintext_db, temp_dir, encryption_key):
    """Test migrating plaintext database to encrypted format."""
    encrypted_db = temp_dir / "encrypted.db"

    # Migrate
    await migrate_plaintext_to_encrypted(plaintext_db, encrypted_db, encryption_key)

    # Verify encrypted database exists
    enc_path = encrypted_db.with_suffix(encrypted_db.suffix + ".enc")
    assert enc_path.exists(), "Encrypted database should exist"

    # Open and verify data
    db = EncryptedSQLite(encrypted_db, encryption_key=encryption_key)
    await db.connect()

    cursor = db.execute("SELECT * FROM test_data")
    rows = cursor.fetchall()

    assert len(rows) == 2
    assert rows[0]["name"] == "test1"
    assert rows[0]["value"] == 100
    assert rows[1]["name"] == "test2"
    assert rows[1]["value"] == 200

    await db.close()


@pytest.mark.asyncio
async def test_verify_encrypted_database(temp_dir, encryption_key):
    """Test encrypted database verification utility."""
    db_path = temp_dir / "test.db"

    # Create encrypted database
    db = EncryptedSQLite(db_path, encryption_key=encryption_key)
    await db.connect()

    db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
    await db.commit()
    await db.close()

    # Verify with correct key
    is_valid = await verify_encrypted_database(db_path, encryption_key)

    assert is_valid is True

    # Verify with wrong key
    is_valid_wrong = await verify_encrypted_database(db_path, "wrong_key_32_characters_____")

    assert is_valid_wrong is False


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_error_when_key_required_but_missing(temp_dir):
    """Test error when encryption required but key not provided."""
    db_path = temp_dir / "test.db"

    # Don't set SQLCIPHER_KEY environment variable
    key = os.environ.get("SQLCIPHER_KEY")
    if key:
        del os.environ["SQLCIPHER_KEY"]

    try:
        with pytest.raises(EncryptionKeyError, match="Encryption key not found"):
            EncryptedSQLite(db_path, require_encryption=True)
    finally:
        # Restore environment variable if it existed
        if key:
            os.environ["SQLCIPHER_KEY"] = key


@pytest.mark.asyncio
async def test_executemany(temp_dir, encryption_key):
    """Test executemany for batch operations."""
    db_path = temp_dir / "test.db"

    db = EncryptedSQLite(db_path, encryption_key=encryption_key)
    await db.connect()

    db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")

    # Batch insert
    data = [("value1",), ("value2",), ("value3",)]
    db.executemany("INSERT INTO test (value) VALUES (?)", data)
    await db.commit()

    # Verify
    cursor = db.execute("SELECT * FROM test")
    rows = cursor.fetchall()

    assert len(rows) == 3

    await db.close()


@pytest.mark.asyncio
async def test_rollback(temp_dir, encryption_key):
    """Test transaction rollback."""
    db_path = temp_dir / "test.db"

    db = EncryptedSQLite(db_path, encryption_key=encryption_key)
    await db.connect()

    db.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, value TEXT)")
    await db.commit()

    # Insert data
    db.execute("INSERT INTO test (value) VALUES (?)", ("before_rollback",))
    await db.commit()

    # Start transaction
    db.execute("INSERT INTO test (value) VALUES (?)", ("after_rollback",))

    # Rollback
    await db.rollback()

    # Verify only first insert exists
    cursor = db.execute("SELECT * FROM test")
    rows = cursor.fetchall()

    assert len(rows) == 1
    assert rows[0]["value"] == "before_rollback"

    await db.close()
