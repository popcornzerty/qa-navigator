"""Schema evolution against a database that already holds rows.

The rest of the suite starts from an empty file, so it exercises `create_all` and never
the migration paths. These tests build the *previous* schema by hand, put a row in it,
and then migrate — which is the only situation the user's own database is ever in.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, inspect

from qa_engine.migrations import ensure_schema

# `playwright_tests` as it stood before tests could be imported from a repository: both
# foreign keys mandatory, and none of the execution-context columns.
LEGACY_SCHEMA = """
CREATE TABLE playwright_tests (
    id VARCHAR(40) NOT NULL,
    project_id VARCHAR(40) NOT NULL,
    user_story_id VARCHAR(40) NOT NULL,
    gherkin_scenario_id VARCHAR(40) NOT NULL,
    scenario VARCHAR(500) NOT NULL,
    file TEXT NOT NULL,
    source TEXT NOT NULL,
    test_status VARCHAR(20) NOT NULL,
    last_run DATETIME,
    duration_ms INTEGER NOT NULL,
    result JSON NOT NULL,
    PRIMARY KEY (id)
);
CREATE INDEX ix_playwright_tests_project_id ON playwright_tests (project_id);
CREATE INDEX ix_playwright_tests_user_story_id ON playwright_tests (user_story_id);
CREATE INDEX ix_playwright_tests_gherkin_scenario_id ON playwright_tests (gherkin_scenario_id);
"""

LEGACY_ROW = (
    "pw-001",
    "prj-1",
    "US-001",
    "US-001-SC-1",
    "Lancer l'analyse",
    "tests/us-001.spec.ts",
    "// spec",
    "passed",
    None,
    1432,
    "{}",
)


def _legacy_database(tmp_path: Path) -> Path:
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.executescript(LEGACY_SCHEMA)
    connection.execute(
        "INSERT INTO playwright_tests VALUES (?,?,?,?,?,?,?,?,?,?,?)", LEGACY_ROW
    )
    connection.commit()
    connection.close()
    return path


def _migrate(path: Path) -> None:
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        ensure_schema(engine)
    finally:
        engine.dispose()


def test_a_mandatory_foreign_key_becomes_optional(tmp_path: Path):
    path = _legacy_database(tmp_path)
    _migrate(path)

    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        columns = {item["name"]: item for item in inspect(engine).get_columns("playwright_tests")}
    finally:
        engine.dispose()
    assert columns["user_story_id"]["nullable"]
    assert columns["gherkin_scenario_id"]["nullable"]


def test_existing_rows_survive_the_rebuild(tmp_path: Path):
    """A rebuild that loses execution history is worse than no rebuild at all."""
    path = _legacy_database(tmp_path)
    _migrate(path)

    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT id, test_status, duration_ms, file FROM playwright_tests"
        ).fetchall()
    finally:
        connection.close()
    assert row == [("pw-001", "passed", 1432, "tests/us-001.spec.ts")]


def test_new_columns_are_filled_with_the_model_default(tmp_path: Path):
    """An empty string would leave the row with a provenance the app does not know."""
    path = _legacy_database(tmp_path)
    _migrate(path)

    connection = sqlite3.connect(path)
    try:
        origin, working_directory = connection.execute(
            "SELECT origin, working_directory FROM playwright_tests"
        ).fetchone()
    finally:
        connection.close()
    assert origin == "generated"
    assert working_directory == ""


def test_indexes_are_carried_over(tmp_path: Path):
    """Renaming a table keeps its indexes, which then collide with the recreated ones."""
    path = _legacy_database(tmp_path)
    _migrate(path)

    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        names = {item["name"] for item in inspect(engine).get_indexes("playwright_tests")}
    finally:
        engine.dispose()
    assert "ix_playwright_tests_user_story_id" in names
    assert "ix_playwright_tests_project_id" in names


def test_no_backup_table_is_left_behind(tmp_path: Path):
    path = _legacy_database(tmp_path)
    _migrate(path)

    connection = sqlite3.connect(path)
    try:
        leftovers = connection.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE '%backup%'"
        ).fetchall()
    finally:
        connection.close()
    assert leftovers == []


def test_migrating_twice_changes_nothing(tmp_path: Path):
    """Every restart runs this; the second one must be a no-op."""
    path = _legacy_database(tmp_path)
    _migrate(path)

    connection = sqlite3.connect(path)
    schema = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='playwright_tests'"
    ).fetchone()
    connection.close()

    _migrate(path)

    connection = sqlite3.connect(path)
    try:
        assert (
            connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='playwright_tests'"
            ).fetchone()
            == schema
        )
        assert connection.execute("SELECT COUNT(*) FROM playwright_tests").fetchone()[0] == 1
    finally:
        connection.close()


def test_the_migrator_sees_the_schema_without_the_caller_importing_models(tmp_path: Path):
    """`Base.metadata` fills as a side effect of defining the models.

    A caller that has not imported them used to hand this module an empty schema, and
    every check then found nothing to do and reported success.
    """
    path = _legacy_database(tmp_path)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    try:
        from qa_engine.database import Base

        assert "playwright_tests" in Base.metadata.tables
    finally:
        engine.dispose()
