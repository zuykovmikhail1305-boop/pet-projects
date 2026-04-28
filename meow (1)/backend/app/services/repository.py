import json
import uuid
from datetime import datetime, UTC
from typing import Any

from app.core.db import get_conn


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def create_chat(title: str) -> dict[str, Any]:
    chat_id = str(uuid.uuid4())
    ts = now_iso()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO chats (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (chat_id, title, ts, ts),
        )
    return get_chat(chat_id)


def list_chats() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at, updated_at FROM chats ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_chat(chat_id: str) -> dict[str, Any] | None:
    with get_conn() as conn:
        chat = conn.execute(
            "SELECT id, title, created_at, updated_at FROM chats WHERE id = ?", (chat_id,)
        ).fetchone()
        if not chat:
            return None
        messages = conn.execute(
            "SELECT id, role, kind, content, meta_json, created_at FROM messages WHERE chat_id = ? ORDER BY created_at ASC",
            (chat_id,),
        ).fetchall()
    payload = dict(chat)
    payload["messages"] = [
        {
            "id": row["id"],
            "role": row["role"],
            "kind": row["kind"],
            "content": row["content"],
            "meta": json.loads(row["meta_json"]) if row["meta_json"] else {},
            "created_at": row["created_at"],
        }
        for row in messages
    ]
    return payload


def append_message(chat_id: str, role: str, kind: str, content: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    message_id = str(uuid.uuid4())
    ts = now_iso()
    meta_json = json.dumps(meta or {}, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO messages (id, chat_id, role, kind, content, meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, chat_id, role, kind, content, meta_json, ts),
        )
        conn.execute("UPDATE chats SET updated_at = ? WHERE id = ?", (ts, chat_id))
    return {
        "id": message_id,
        "chat_id": chat_id,
        "role": role,
        "kind": kind,
        "content": content,
        "meta": meta or {},
        "created_at": ts,
    }
