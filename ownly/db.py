"""SQLite access: one connection per request, opened lazily."""
import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


# Columns added after the first release: (table, column, type).
MIGRATIONS = [
    ("listings", "latitude", "REAL"),
    ("listings", "longitude", "REAL"),
]


def init(path: str) -> None:
    conn = connect(path)
    with conn:
        conn.executescript(SCHEMA.read_text())
        for table, column, kind in MIGRATIONS:
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    conn.close()


def one(sql: str, *args):
    return get().execute(sql, args).fetchone()


def all_(sql: str, *args) -> list:
    return get().execute(sql, args).fetchall()


def run(sql: str, *args) -> int:
    """Execute and commit; returns the new row id for inserts."""
    conn = get()
    with conn:
        cur = conn.execute(sql, args)
    return cur.lastrowid
