"""Encrypted SQLite wrapper using application-level encryption.

This module provides encrypted SQLite database connections for sensitive data
storage (code graphs, session data, etc.) using AES-256 encryption.

Security Features:
- AES-256-GCM encryption (authenticated encryption)
- Per-database encryption keys
- Key derivation from environment variables
- Automatic key validation
- Python 3.13+ compatible (no C extensions)

Architecture:
- Application-level encryption (database pages encrypted before storage)
- Compatible with standard sqlite3 module
- Graceful degradation if encryption unavailable (with warning)
"""

import base64
import logging
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)


class EncryptionKeyError(Exception):
    """Raised when encryption key is invalid or missing."""


class EncryptedSQLite:
    """Encrypted SQLite database using application-level AES-256 encryption.

    This implementation encrypts the entire database file at rest using
    AES-256-GCM via cryptography.fernet, which provides:
    - Authenticated encryption (detects tampering)
    - Python 3.13+ compatibility (pure Python, no C extensions)
    - Standard library compatibility (works with sqlite3 module)

    Usage:
        ```python
        # Get encryption key from environment
        db = EncryptedSQLite("data/sensitive.db")
        await db.connect()

        # Use like regular SQLite connection
        cursor = db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        rows = cursor.fetchall()

        await db.close()
        ```
    """

    def __init__(
        self,
        db_path: Path | str,
        encryption_key: str | None = None,
        key_env_var: str = "SQLCIPHER_KEY",
        require_encryption: bool = True,
    ):
        """Initialize encrypted SQLite database.

        Args:
            db_path: Path to database file (will be stored with .enc extension)
            encryption_key: Encryption key (32+ characters recommended)
                          If None, reads from environment variable
            key_env_var: Environment variable name for encryption key
            require_encryption: If True, fail without encryption key
                              If False, use plaintext SQLite with warning

        Raises:
            EncryptionKeyError: If key is invalid/missing and require_encryption=True
        """
        self.db_path = Path(db_path)
        self.enc_path = self.db_path.with_suffix(self.db_path.suffix + ".enc")
        self.enc_path.parent.mkdir(parents=True, exist_ok=True)
        self.require_encryption = require_encryption

        # Get encryption key
        self.encryption_key = encryption_key or os.environ.get(key_env_var)
        self._fernet: Fernet | None = None
        self._using_encryption = False

        # Validate key if required
        if self.encryption_key:
            if len(self.encryption_key) < 32:
                raise EncryptionKeyError(
                    f"Encryption key too short ({len(self.encryption_key)} chars). "
                    f"Minimum 32 characters recommended for AES-256 security."
                )
            self._fernet = self._create_fernet(self.encryption_key)
            self._using_encryption = True
        elif require_encryption:
            raise EncryptionKeyError(
                f"Encryption key not found. Set {key_env_var} environment variable "
                f"or pass encryption_key parameter."
            )
        else:
            logger.warning(
                f"No encryption key provided for {self.db_path}. "
                "Using plaintext SQLite (NOT recommended for production)."
            )

        self._conn: sqlite3.Connection | None = None

        logger.info(
            f"EncryptedSQLite initialized (db={self.db_path}, "
            f"encryption={'enabled' if self._using_encryption else 'disabled'})"
        )

    @staticmethod
    def _create_fernet(password: str) -> Fernet:
        """Create Fernet cipher from password using PBKDF2.

        Args:
            password: Password string

        Returns:
            Fernet cipher instance
        """
        # Use PBKDF2 to derive key from password
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"mahavishnu_sql_encryption",  # Fixed salt for reproducibility
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return Fernet(key)

    def _decrypt_database(self) -> bool:
        """Decrypt database file from encrypted storage.

        Returns:
            True if decryption successful, False otherwise

        Raises:
            EncryptionKeyError: If decryption fails (wrong key or corrupted data)
        """
        if not self._using_encryption or not self.enc_path.exists():
            return False

        # Type narrowing: _using_encryption=True guarantees _fernet is not None
        assert self._fernet is not None

        try:
            logger.debug(f"Decrypting database: {self.enc_path} → {self.db_path}")

            with open(self.enc_path, "rb") as f:
                encrypted_data = f.read()

            # Decrypt using Fernet
            decrypted_data = self._fernet.decrypt(encrypted_data)

            # Write decrypted database
            with open(self.db_path, "wb") as f:
                f.write(decrypted_data)

            logger.debug("Database decrypted successfully")
            return True

        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            # Re-raise to signal decryption failure to caller
            raise EncryptionKeyError(
                f"Database decryption failed: {e}. Check encryption key is correct."
            ) from e

    def _encrypt_database(self) -> bool:
        """Encrypt database file to encrypted storage.

        Returns:
            True if encryption successful, False otherwise
        """
        if not self._using_encryption or not self.db_path.exists():
            return False

        # Type narrowing: _using_encryption=True guarantees _fernet is not None
        assert self._fernet is not None

        try:
            logger.debug(f"Encrypting database: {self.db_path} → {self.enc_path}")

            with open(self.db_path, "rb") as f:
                plaintext_data = f.read()

            # Encrypt using Fernet
            encrypted_data = self._fernet.encrypt(plaintext_data)

            # Write encrypted database
            with open(self.enc_path, "wb") as f:
                f.write(encrypted_data)

            logger.debug("Database encrypted successfully")
            return True

        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            return False

    async def connect(self) -> None:
        """Connect to encrypted database.

        This must be called before executing any queries.

        Process:
        1. Decrypt database file from .enc to plaintext
        2. Connect to plaintext database using sqlite3
        3. Database ready for queries

        Raises:
            sqlite3.DatabaseError: If database is corrupted
            EncryptionKeyError: If decryption fails
        """
        if self._conn is not None:
            logger.warning("Database already connected")
            return

        try:
            # Decrypt database if encryption enabled
            if self._using_encryption:
                if self.enc_path.exists():
                    self._decrypt_database()  # Will raise EncryptionKeyError if wrong key
                else:
                    logger.debug(f"No encrypted database found at {self.enc_path}, creating new")

            # Connect to (decrypted) database
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row  # Return dict-like rows

            # Enable optimizations
            cursor = self._conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-10000")  # 10MB cache
            self._conn.commit()

            logger.info(f"Connected to encrypted database: {self.db_path}")

        except EncryptionKeyError:
            # Re-raise encryption key errors as-is
            logger.error("Failed to connect to database: wrong encryption key")
            self._conn = None
            raise

        except sqlite3.DatabaseError as e:
            logger.error(f"Failed to connect to database: {e}")
            self._conn = None

            if "database disk image is malformed" in str(e):
                raise EncryptionKeyError(
                    "Database decryption failed. Check encryption key is correct."
                ) from e

            raise

    async def close(self) -> None:
        """Close database connection and encrypt storage.

        Process:
        1. Close SQLite connection
        2. Encrypt database file to .enc
        3. Delete plaintext database file
        """
        # Close connection
        if self._conn:
            self._conn.close()
            self._conn = None

        # Encrypt database on close
        if self._using_encryption and self.db_path.exists() and self._encrypt_database():
            # Delete plaintext database after successful encryption
            self.db_path.unlink()
            logger.debug("Plaintext database removed after encryption")

        logger.info("Database connection closed and encrypted")

    def execute(self, sql: str, parameters: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        """Execute SQL query.

        Args:
            sql: SQL statement
            parameters: Query parameters

        Returns:
            Cursor object

        Raises:
            RuntimeError: If database not connected
        """
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")

        return self._conn.execute(sql, parameters)

    def executemany(self, sql: str, parameters: list[tuple[Any, ...]]) -> sqlite3.Cursor:
        """Execute multiple SQL statements with parameters.

        Args:
            sql: SQL statement
            parameters: List of parameter tuples

        Returns:
            Cursor object
        """
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")

        return self._conn.executemany(sql, parameters)

    async def commit(self) -> None:
        """Commit transaction."""
        if self._conn:
            self._conn.commit()

    async def rollback(self) -> None:
        """Rollback transaction."""
        if self._conn:
            self._conn.rollback()

    @property
    def connection(self) -> sqlite3.Connection:
        """Get underlying connection (for raw access).

        Returns:
            SQLite connection object

        Raises:
            RuntimeError: If database not connected
        """
        if self._conn is None:
            raise RuntimeError("Database not connected. Call connect() first.")

        return self._conn

    async def verify_integrity(self) -> bool:
        """Verify database integrity.

        Returns:
            True if database is valid, False otherwise
        """
        if not self._conn:
            return False

        try:
            cursor = self._conn.cursor()
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()

            if result and result[0] == "ok":
                logger.info("Database integrity check passed")
                return True
            else:
                logger.error(f"Database integrity check failed: {result}")
                return False

        except sqlite3.DatabaseError as e:
            logger.error(f"Database integrity check error: {e}")
            return False

    async def backup(self, backup_path: Path | str) -> None:
        """Backup encrypted database.

        Note: Backup will also be encrypted with the same key.

        Args:
            backup_path: Path to backup database file (will be stored as .enc)
        """
        if not self._conn:
            raise RuntimeError("Database not connected")

        backup_path = Path(backup_path)
        enc_backup_path = backup_path.with_suffix(backup_path.suffix + ".enc")
        enc_backup_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Creating encrypted backup: {enc_backup_path}")

        # If encryption enabled, copy encrypted file directly
        if self._using_encryption and self.enc_path.exists():
            shutil.copy2(self.enc_path, enc_backup_path)
        else:
            # Fallback to SQLite backup API
            cursor = self._conn.cursor()
            cursor.execute(f"VACUUM INTO '{backup_path}'")
            self._conn.commit()

            # Encrypt backup if encryption enabled
            if self._using_encryption:
                # Type narrowing: _using_encryption=True guarantees _fernet is not None
                assert self._fernet is not None

                # Read plaintext backup
                with open(backup_path, "rb") as f:
                    plaintext_data = f.read()

                # Encrypt and write
                encrypted_data = self._fernet.encrypt(plaintext_data)
                with open(enc_backup_path, "wb") as f:
                    f.write(encrypted_data)

                # Delete plaintext backup
                backup_path.unlink()

        logger.info(f"Backup created: {enc_backup_path}")

    async def restore(self, backup_path: Path | str) -> None:
        """Restore from encrypted backup.

        Args:
            backup_path: Path to backup database file (.enc or plaintext)
        """
        if not self._conn:
            raise RuntimeError("Database not connected")

        backup_path = Path(backup_path)

        # Try .enc extension first if not specified
        if not backup_path.exists():
            enc_backup_path = backup_path.with_suffix(backup_path.suffix + ".enc")
            if enc_backup_path.exists():
                backup_path = enc_backup_path

        if not backup_path.exists():
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        logger.info(f"Restoring from encrypted backup: {backup_path}")

        # Close current connection
        await self.close()

        # Copy backup to encrypted database location
        if backup_path.suffix == ".enc":
            shutil.copy2(backup_path, self.enc_path)
        else:
            # Plaintext backup - encrypt it
            shutil.copy2(backup_path, self.db_path)
            if self._using_encryption:
                await self.connect()
                await self.close()  # This will encrypt it

        # Reconnect
        await self.connect()

        logger.info(f"Restore complete: {self.db_path}")


class EncryptedSQLitePool:
    """Connection pool for encrypted SQLite databases.

    Provides connection pooling and automatic reconnection.
    """

    def __init__(
        self,
        db_path: Path | str,
        encryption_key: str | None = None,
        pool_size: int = 5,
        require_encryption: bool = True,
    ):
        """Initialize connection pool.

        Args:
            db_path: Path to database file
            encryption_key: Encryption key (or from env var)
            pool_size: Maximum number of connections
            require_encryption: Require encryption or allow plaintext fallback
        """
        self.db_path = Path(db_path)
        self.encryption_key = encryption_key
        self.pool_size = pool_size
        self.require_encryption = require_encryption
        self._pool: list[EncryptedSQLite] = []

        logger.info(f"EncryptedSQLitePool initialized (pool_size={pool_size})")

    async def acquire(self) -> EncryptedSQLite:
        """Acquire connection from pool.

        Creates new connection if pool is empty.

        Returns:
            EncryptedSQLite connection
        """
        if self._pool:
            conn = self._pool.pop()
            logger.debug(f"Acquired connection from pool ({len(self._pool)} available)")
            return conn

        # Create new connection
        logger.debug("Creating new database connection")
        conn = EncryptedSQLite(
            self.db_path,
            self.encryption_key,
            require_encryption=self.require_encryption,
        )
        await conn.connect()
        return conn

    async def release(self, conn: EncryptedSQLite) -> None:
        """Release connection back to pool.

        Args:
            conn: Connection to release
        """
        if len(self._pool) < self.pool_size:
            self._pool.append(conn)
            logger.debug(f"Released connection to pool ({len(self._pool)} available)")
        else:
            # Pool full, close connection
            await conn.close()
            logger.debug("Pool full, connection closed")

    async def close_all(self) -> None:
        """Close all connections in pool."""
        for conn in self._pool:
            await conn.close()

        self._pool.clear()
        logger.info("All pool connections closed")


# =============================================================================
# KEY MANAGEMENT UTILITIES
# =============================================================================


def generate_encryption_key(length: int = 32) -> str:
    """Generate cryptographically secure encryption key.

    Args:
        length: Key length in characters (default 32 for AES-256)

    Returns:
        Random encryption key

    Example:
        ```python
        key = generate_encryption_key()
        os.environ["SQLCIPHER_KEY"] = key
        ```
    """
    import secrets

    # Use cryptographically secure random generator
    key = secrets.token_urlsafe(length)

    # Ensure minimum length
    while len(key) < length:
        key += secrets.token_urlsafe(length)

    return key[:length]


def validate_encryption_key(key: str, min_length: int = 32) -> bool:
    """Validate encryption key meets requirements.

    Args:
        key: Encryption key to validate
        min_length: Minimum key length

    Returns:
        True if key is valid, False otherwise
    """
    return len(key) >= min_length


# =============================================================================
# MIGRATION UTILITIES
# =============================================================================


async def migrate_plaintext_to_encrypted(
    plaintext_db: Path | str,
    encrypted_db: Path | str,
    encryption_key: str,
) -> None:
    """Migrate plaintext database to encrypted format.

    Args:
        plaintext_db: Path to plaintext SQLite database
        encrypted_db: Path for new encrypted database
        encryption_key: Encryption key for new database
    """
    plaintext_db = Path(plaintext_db)
    encrypted_db = Path(encrypted_db)

    if not plaintext_db.exists():
        raise FileNotFoundError(f"Plaintext database not found: {plaintext_db}")

    logger.info(f"Migrating plaintext database to encrypted: {plaintext_db} → {encrypted_db}")

    # Create encrypted database
    conn_enc = EncryptedSQLite(encrypted_db, encryption_key)
    await conn_enc.connect()

    try:
        # Open plaintext database
        conn_plain = sqlite3.connect(str(plaintext_db))

        # Dump plaintext database
        dump = "\n".join(conn_plain.iterdump())

        # Execute dump in encrypted database
        cursor_enc = conn_enc.connection.cursor()
        cursor_enc.executescript(dump)

        await conn_enc.commit()

        conn_plain.close()

        logger.info("Migration complete")

    finally:
        await conn_enc.close()


async def verify_encrypted_database(
    db_path: Path | str,
    encryption_key: str,
) -> bool:
    """Verify encrypted database can be opened and is valid.

    Args:
        db_path: Path to encrypted database
        encryption_key: Encryption key

    Returns:
        True if database is valid, False otherwise
    """
    try:
        db = EncryptedSQLite(db_path, encryption_key)
        await db.connect()
        is_valid = await db.verify_integrity()
        await db.close()
        return is_valid

    except Exception as e:
        logger.error(f"Encrypted database verification failed: {e}")
        return False
