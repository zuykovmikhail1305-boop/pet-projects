from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any

from app.core.config import settings


def _ensure_parent_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


_ensure_parent_dir(settings.db_path)
os.makedirs(settings.uploads_dir, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def connection_ctx():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connection_ctx() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                meta_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
            )
            """
        )


def create_chat(title: str) -> dict[str, Any]:
    with connection_ctx() as conn:
        cursor = conn.execute(
            "INSERT INTO chats (title) VALUES (?)",
            (title,),
        )
        chat_id = cursor.lastrowid
        row = conn.execute(
            "SELECT id, title, created_at FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
    return dict(row)


def update_chat_title(chat_id: int, title: str) -> None:
    with connection_ctx() as conn:
        conn.execute(
            "UPDATE chats SET title = ? WHERE id = ?",
            (title, chat_id),
        )


def list_chats() -> list[dict[str, Any]]:
    with connection_ctx() as conn:
        rows = conn.execute(
            """
            SELECT
                c.id,
                c.title,
                c.created_at
            FROM chats c
            ORDER BY c.id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def add_message(chat_id: int, kind: str, content: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = meta or {}
    with connection_ctx() as conn:
        cursor = conn.execute(
            """
            INSERT INTO messages (chat_id, kind, content, meta_json)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, kind, content, json.dumps(meta, ensure_ascii=False)),
        )
        message_id = cursor.lastrowid
        row = conn.execute(
            """
            SELECT id, chat_id, kind, content, meta_json, created_at
            FROM messages
            WHERE id = ?
            """,
            (message_id,),
        ).fetchone()
    return _row_to_message(row)


def get_chat(chat_id: int) -> dict[str, Any] | None:
    with connection_ctx() as conn:
        chat_row = conn.execute(
            "SELECT id, title, created_at FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
        if not chat_row:
            return None

        message_rows = conn.execute(
            """
            SELECT id, chat_id, kind, content, meta_json, created_at
            FROM messages
            WHERE chat_id = ?
            ORDER BY id ASC
            """,
            (chat_id,),
        ).fetchall()

    return {
        "id": chat_row["id"],
        "title": chat_row["title"],
        "created_at": chat_row["created_at"],
        "messages": [_row_to_message(row) for row in message_rows],
    }


def get_recent_messages(chat_id: int, limit: int = 8) -> list[dict[str, Any]]:
    with connection_ctx() as conn:
        rows = conn.execute(
            """
            SELECT id, chat_id, kind, content, meta_json, created_at
            FROM messages
            WHERE chat_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        ).fetchall()

    messages = [_row_to_message(row) for row in rows]
    messages.reverse()
    return messages


def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
    meta = {}
    raw_meta = row["meta_json"]
    if raw_meta:
        try:
            meta = json.loads(raw_meta)
        except Exception:
            meta = {}

    return {
        "id": row["id"],
        "chat_id": row["chat_id"],
        "kind": row["kind"],
        "content": row["content"],
        "meta": meta,
        "created_at": row["created_at"],
    }