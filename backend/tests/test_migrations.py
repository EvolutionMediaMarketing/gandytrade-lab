"""Database upgrades: the migrations build exactly the tables the code expects."""

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db import Base


def _diff(engine):
    from app import models  # noqa: F401

    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"compare_type": True})
        return compare_metadata(ctx, Base.metadata)


def test_migrations_match_the_models(client):
    from app.db import get_engine

    assert _diff(get_engine()) == []


def test_existing_phase1_database_is_upgraded(tmp_path, monkeypatch):
    """A database made the old way (create_all, no migration record) upgrades cleanly and keeps its rows."""
    from app import config, db

    url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64) NOT NULL UNIQUE, "
                             "password_hash VARCHAR(255) NOT NULL, totp_secret VARCHAR(64) NOT NULL, "
                             "totp_last_step BIGINT NOT NULL, failed_logins INTEGER NOT NULL, "
                             "locked_until DATETIME, created_at DATETIME NOT NULL)"))
        conn.execute(sa.text("INSERT INTO users VALUES (1, 'gandy', 'h', 's', 0, 0, NULL, '2026-09-30 10:00:00')"))
        conn.execute(sa.text("CREATE TABLE fetch_state (id INTEGER PRIMARY KEY, source VARCHAR(32) NOT NULL, "
                             "symbol VARCHAR(32) NOT NULL, timeframe VARCHAR(8) NOT NULL, fetched_at DATETIME NOT NULL, "
                             "CONSTRAINT uq_fetch_state UNIQUE (source, symbol, timeframe))"))
    engine.dispose()

    monkeypatch.setenv("GT_DATABASE_URL", url)
    config.get_settings.cache_clear()
    db.reset_engine()
    try:
        db.init_db()
        db.init_db()  # running again is harmless
        with db.get_engine().connect() as conn:
            assert conn.execute(sa.text("SELECT username FROM users")).scalar() == "gandy"
            assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() is not None
            cols = {c["name"] for c in sa.inspect(conn).get_columns("fetch_state")}
            assert "deep_fetched_at" in cols
    finally:
        db.reset_engine()
        config.get_settings.cache_clear()
