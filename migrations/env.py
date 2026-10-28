from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

import app.models  # noqa: F401  (registers all ORM models on Base.metadata)
from app.base.models.mysql_base import Base
from app.core.database import make_engine
from config.database import db_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
URL = db_settings.url()


def run_migrations_offline() -> None:
    context.configure(url=URL, target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = make_engine(URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=URL.startswith("sqlite"))
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
