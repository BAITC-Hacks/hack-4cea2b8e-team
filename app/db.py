"""SQLite без ORM. Для 5 часов этого достаточно, а эксперту нечего настраивать."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from . import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL DEFAULT 'item',
    title      TEXT NOT NULL,
    payload    TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    prompt     TEXT NOT NULL,
    response   TEXT NOT NULL,
    seconds    REAL NOT NULL,
    demo       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def connect() -> sqlite3.Connection:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with connect() as conn:
        conn.executescript(_SCHEMA)


def add_item(title: str, payload: dict[str, Any] | None = None, kind: str = "item") -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO items (kind, title, payload) VALUES (?, ?, ?)",
            (kind, title, json.dumps(payload or {}, ensure_ascii=False)),
        )
        return int(cur.lastrowid)


def list_items(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM items ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {**dict(r), "payload": json.loads(r["payload"])} for r in rows
    ]


def delete_item(item_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))


def log_llm_call(kind: str, prompt: str, response: str, seconds: float, demo: bool) -> None:
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO llm_calls (kind, prompt, response, seconds, demo)"
                " VALUES (?, ?, ?, ?, ?)",
                (kind, prompt[:8000], response[:8000], seconds, int(demo)),
            )
    except Exception:
        pass  # логирование не должно ронять основной сценарий


def stats() -> dict[str, Any]:
    with connect() as conn:
        calls = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(seconds),0) s FROM llm_calls").fetchone()
        items = conn.execute("SELECT COUNT(*) c FROM items").fetchone()
    return {
        "items": items["c"],
        "llm_calls": calls["c"],
        "llm_seconds": round(calls["s"], 2),
    }
