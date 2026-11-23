"""Updating the database: all or nothing, with a copy from before."""

import sqlite3

import pytest

from app import db as db_module
from app.db import MIGRATIONS, Database


def columns(path, table: str) -> set[str]:
    with Database(path).connect() as conn:
        return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


@pytest.fixture
def current(tmp_path):
    path = tmp_path / "clipping.db"
    Database(path).migrate()
    with Database(path).connect() as conn:
        conn.execute("INSERT INTO projects (name) VALUES ('keep me')")
    return path


def test_an_interrupted_migration_changes_nothing_and_can_run_again(current, monkeypatch):
    broken = "ALTER TABLE clips ADD COLUMN new_one TEXT;\nUPDATE projects SET name = 'changed';\nSELECT * FROM missing_table;"
    monkeypatch.setattr(db_module, "MIGRATIONS", [*MIGRATIONS, broken])
    with pytest.raises(sqlite3.OperationalError, match="missing_table"):
        Database(current).migrate()
    assert Database(current).schema_version() == len(MIGRATIONS)
    assert "new_one" not in columns(current, "clips")
    with Database(current).connect() as conn:
        assert conn.execute("SELECT name FROM projects").fetchone()[0] == "keep me"

    fixed = "ALTER TABLE clips ADD COLUMN new_one TEXT; ALTER TABLE clips ADD COLUMN new_two TEXT;"
    monkeypatch.setattr(db_module, "MIGRATIONS", [*MIGRATIONS, fixed])
    assert Database(current).migrate() == len(MIGRATIONS) + 1
    assert {"new_one", "new_two"} <= columns(current, "clips")


def test_a_copy_is_kept_before_updating(current, monkeypatch):
    monkeypatch.setattr(db_module, "MIGRATIONS", [*MIGRATIONS, "DELETE FROM projects;"])
    Database(current).migrate()
    copy = sqlite3.connect(current.with_name(f"{current.name}.v{len(MIGRATIONS)}.bak"))
    assert copy.execute("SELECT name FROM projects").fetchone()[0] == "keep me"
    copy.close()


def test_no_copy_when_there_is_nothing_to_update(current):
    Database(current).migrate()
    assert not list(current.parent.glob("*.bak"))


def test_every_migration_step_can_be_the_last(tmp_path, monkeypatch):
    """From each older version to the newest."""
    for version in range(1, len(MIGRATIONS)):
        path = tmp_path / f"v{version}.db"
        monkeypatch.setattr(db_module, "MIGRATIONS", MIGRATIONS[:version])
        Database(path).migrate()
        monkeypatch.setattr(db_module, "MIGRATIONS", MIGRATIONS)
        assert Database(path).migrate() == len(MIGRATIONS)


def test_a_database_from_a_newer_app_is_refused(current):
    with Database(current).connect() as conn:
        conn.execute("PRAGMA user_version = 999")
    with pytest.raises(RuntimeError, match="newer version of the app"):
        Database(current).migrate()


def test_foreign_keys_are_on_outside_migrations(current):
    with Database(current).connect() as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sources (project_id, origin) VALUES (999, 'file')")
