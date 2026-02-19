"""Alembic migration environment for Mahavishnu.

Supports async migrations with asyncpg and environment-based configuration.
"""

from __future__ import annotations

import asyncio
import logging
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Add your model's MetaData object here for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = None

# Other values from the config, defined by the needs of env.py
logger = logging.getLogger(__name__)


def get_database_url() -> str:
    """Get database URL from environment or config."""
    # Priority: Environment variable > alembic.ini
    db_url = os.getenv("MAHAVISHNU_DB_URL")
    if db_url:
        return db_url

    # Build from individual components
    host = os.getenv("MAHAVISHNU_DB_HOST", "localhost")
    port = os.getenv("MAHAVISHNU_DB_PORT", "5432")
    database = os.getenv("MAHAVISHNU_DB_NAME", "mahavishnu")
    user = os.getenv("MAHAVISHNU_DB_USER", "mahavishnu")
    password = os.getenv("MAHAVISHNU_DB_PASSWORD", "")

    if password:
        return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"
    return f"postgresql+asyncpg://{user}@{host}:{port}/{database}"


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine,
    though an Engine is acceptable here as well.

    Calls to context.execute() here emit the given string to the script output.
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with the given connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine.

    In this scenario we need to create an Engine and associate
    a connection with the context.
    """
    # Get configuration for async engine
    db_url = get_database_url()

    # Convert postgresql:// to postgresql+asyncpg:// if needed
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = db_url

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
