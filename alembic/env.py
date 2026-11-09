from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool, text

import app.core.models_registry  # noqa: F401  (registers every module's tables)
from app.core.config import get_settings
from app.core.db import MIGRATOR_ROLE
from app.core.model_base import Base

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def become_migrator(connection: Connection) -> None:
    """Run as the migrator so every table it creates has the same owner.

    Only once migration 0004 has handed this database to the migrator: before that the role may
    not exist yet, or exist (created for another database on the server) and own nothing here.
    Fails if the connected user is not a member of the migrator role.
    """
    owner = connection.scalar(
        text("SELECT nspowner::regrole::text FROM pg_namespace WHERE nspname = 'platform'")
    )
    if owner == MIGRATOR_ROLE:
        connection.execute(text(f"SET ROLE {MIGRATOR_ROLE}"))
    connection.commit()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        become_migrator(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
