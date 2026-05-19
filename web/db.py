from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "bot.sqlite"


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS candidates (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tweet_id TEXT UNIQUE,
              tweet_url TEXT,
              username TEXT,
              content TEXT,
              source TEXT,
              query TEXT,
              status TEXT NOT NULL,
              matched_keywords TEXT,
              matched_topics TEXT,
              reply_text TEXT,
              edited_reply_text TEXT,
              metadata_json TEXT,
              approved_by TEXT,
              approved_at TEXT,
              published_at TEXT,
              publish_result TEXT,
              error_message TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS audit_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              candidate_id INTEGER,
              action TEXT NOT NULL,
              details TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS scheduler_state (
              id INTEGER PRIMARY KEY CHECK (id = 1),
              enabled INTEGER DEFAULT 1,
              paused INTEGER DEFAULT 0,
              last_run_at TEXT,
              next_run_at TEXT,
              last_status TEXT,
              last_error TEXT,
              updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            INSERT OR IGNORE INTO scheduler_state(id, enabled, paused, last_status)
            VALUES (1, 1, 0, 'never_run');
            """
        )
        _ensure_columns(conn)


def _ensure_columns(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(candidates)").fetchall()}
    columns = {
        "tweet_url": "TEXT",
        "source": "TEXT",
        "matched_keywords": "TEXT",
        "matched_topics": "TEXT",
        "edited_reply_text": "TEXT",
        "approved_by": "TEXT",
        "approved_at": "TEXT",
        "published_at": "TEXT",
        "publish_result": "TEXT",
        "error_message": "TEXT",
    }
    for name, sql_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE candidates ADD COLUMN {name} {sql_type}")


def add_audit(conn, candidate_id, action, details=None):
    conn.execute(
        "INSERT INTO audit_log(candidate_id, action, details) VALUES (?, ?, ?)",
        (candidate_id, action, json.dumps(details, ensure_ascii=False) if details is not None else None),
    )


def normalize_row(row) -> dict[str, Any]:
    data = dict(row)
    for key in ["metadata_json", "matched_keywords", "matched_topics", "publish_result"]:
        value = data.get(key)
        if isinstance(value, str) and value:
            try:
                data[key] = json.loads(value)
            except Exception:
                pass
    return data


def upsert_candidate(
    conn,
    *,
    tweet_id: str,
    username: str,
    content: str,
    query: str,
    source: str,
    reply_text: str,
    metadata: dict[str, Any],
    matched_keywords: list[str] | None = None,
    matched_topics: list[str] | None = None,
) -> bool:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO candidates(
          tweet_id, tweet_url, username, content, source, query, status,
          matched_keywords, matched_topics, reply_text, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)
        """,
        (
            tweet_id,
            f"https://x.com/{username}/status/{tweet_id}" if username and tweet_id else "",
            username,
            content,
            source,
            query,
            json.dumps(matched_keywords or [], ensure_ascii=False),
            json.dumps(matched_topics or [], ensure_ascii=False),
            reply_text,
            json.dumps(metadata, ensure_ascii=False),
        ),
    )
    return cur.rowcount > 0
