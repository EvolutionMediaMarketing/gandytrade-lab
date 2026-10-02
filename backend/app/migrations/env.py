"""Alembic environment. The app runs migrations itself at start-up (see app/db.py)."""

from alembic import context

from app.db import Base, get_engine
from app import models  # noqa: F401  (register tables)

config = context.config
target_metadata = Base.metadata


def run() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        with get_engine().connect() as conn:
            _configure_and_run(conn)
            conn.commit()
    else:
        _configure_and_run(connection)


def _configure_and_run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite needs table copies to alter columns
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


run()
