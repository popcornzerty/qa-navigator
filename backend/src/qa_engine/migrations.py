"""Minimal schema evolution for the SQLite development database.

Not a replacement for Alembic — it covers the two cases this project actually hits while
the schema is still moving: a new column on an existing table, and a derived table whose
shape changed. Introduce Alembic before the first shared/production deployment.
"""

from __future__ import annotations

import json
import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from qa_engine.database import Base

logger = logging.getLogger(__name__)

# Tables rebuilt from scratch by every analysis. Dropping them loses no user input, so a
# shape change can be applied by recreating them instead of migrating column by column.
DERIVED_TABLES = {"features"}

SQL_TYPES = {
    "VARCHAR": "VARCHAR",
    "TEXT": "TEXT",
    "INTEGER": "INTEGER",
    "FLOAT": "FLOAT",
    "BOOLEAN": "BOOLEAN",
    "DATETIME": "DATETIME",
    "JSON": "JSON",
}


def _column_sql_type(column) -> str:
    compiled = column.type.compile().split("(")[0].upper()
    return SQL_TYPES.get(compiled, "TEXT")


def _sql_literal(value) -> str | None:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    if isinstance(value, (dict, list)):
        return "'" + json.dumps(value).replace("'", "''") + "'"
    return None


def _default_literal(column) -> str | None:
    """Default used to backfill existing rows when a column is added.

    The model's own default wins: filling `branch` or `project_status` with an empty
    string would silently corrupt every existing row.
    """
    default = getattr(column, "default", None)
    if default is not None:
        argument = getattr(default, "arg", None)
        if argument is not None and not callable(argument):
            literal = _sql_literal(argument)
            if literal is not None:
                return literal
        if callable(argument):
            try:
                literal = _sql_literal(argument(None))
            except TypeError:
                literal = None
            if literal is not None:
                return literal

    if column.nullable:
        return "NULL"
    compiled = _column_sql_type(column)
    if compiled in {"INTEGER", "FLOAT"}:
        return "0"
    if compiled == "BOOLEAN":
        return "0"
    if compiled == "JSON":
        return "'{}'"
    if compiled == "DATETIME":
        return "CURRENT_TIMESTAMP"
    return "''"


def ensure_schema(engine: Engine) -> None:
    """Align the physical database with the declarative models."""
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    # 1. Recreate derived tables whose shape drifted from the models.
    for table_name in DERIVED_TABLES & existing_tables:
        table = Base.metadata.tables.get(table_name)
        if table is None:
            continue
        physical = {column["name"] for column in inspector.get_columns(table_name)}
        expected = {column.name for column in table.columns}
        if physical != expected:
            logger.warning("Recreating derived table %s (schema changed)", table_name)
            with engine.begin() as connection:
                connection.execute(text(f"DROP TABLE {table_name}"))
            existing_tables.discard(table_name)

    Base.metadata.create_all(bind=engine)

    # 2. Add columns that appeared on tables holding data we must keep.
    inspector = inspect(engine)
    for table_name, table in Base.metadata.tables.items():
        if table_name not in set(inspector.get_table_names()):
            continue
        physical = {column["name"] for column in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name in physical:
                continue
            statement = (
                f"ALTER TABLE {table_name} ADD COLUMN {column.name} {_column_sql_type(column)}"
            )
            default = _default_literal(column)
            if default and default != "NULL":
                statement += f" NOT NULL DEFAULT {default}"
            logger.warning("Adding column %s.%s", table_name, column.name)
            with engine.begin() as connection:
                connection.execute(text(statement))
