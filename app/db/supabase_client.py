from __future__ import annotations

import os
import psycopg
from typing import Optional


def apply_migration(database_url: str, sql_file_path: str) -> None:
    """Apply a SQL migration file to the target Postgres database."""
    with open(sql_file_path, "r", encoding="utf-8") as f:
        sql = f.read()

    # psycopg3 auto-commits only when explicitly asked
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


# === Lightweight runtime helpers (sync) ===

def _get_db_url() -> Optional[str]:
    return os.getenv("DATABASE_URL")


def create_debate_session(chat_id: int, topic_title: str) -> Optional[str]:
    """Create (or reuse) a topic by title and insert an active debate session. Returns session_id.
    Returns None if DATABASE_URL is missing or on error.
    """
    db_url = _get_db_url()
    if not db_url:
        return None
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                # Get or create topic id
                cur.execute("select id from topics where title = %s limit 1", (topic_title,))
                row = cur.fetchone()
                if row:
                    topic_id = row[0]
                else:
                    cur.execute("insert into topics (title) values (%s) returning id", (topic_title,))
                    topic_id = cur.fetchone()[0]

                # Create session with empty turn_order for now (uuid[])
                cur.execute(
                    """
                    insert into debate_sessions (topic_id, chat_id, status, turn_order)
                    values (%s, %s, 'active', ARRAY[]::uuid[])
                    returning id
                    """,
                    (topic_id, chat_id),
                )
                session_id = cur.fetchone()[0]
            conn.commit()
        return str(session_id)
    except Exception:
        return None


def end_debate_session(session_id: str) -> bool:
    """Mark session as ended."""
    db_url = _get_db_url()
    if not db_url:
        return False
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "update debate_sessions set status='ended', ended_at = now() where id = %s",
                    (session_id,),
                )
            conn.commit()
        return True
    except Exception:
        return False


def insert_message(session_id: str, content: str, telegram_msg_id: Optional[int] = None, role: str = "assistant") -> bool:
    """Insert a message log. bot_id left null; role defaults to 'assistant'."""
    db_url = _get_db_url()
    if not db_url:
        return False
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into messages (session_id, bot_id, role, content, telegram_msg_id)
                    values (%s, NULL, %s, %s, %s)
                    """,
                    (session_id, role, content, telegram_msg_id),
                )
            conn.commit()
        return True
    except Exception:
        return False
