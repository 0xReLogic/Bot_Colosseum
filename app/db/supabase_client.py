from __future__ import annotations

import os
import psycopg
from typing import Optional, List, Dict, Any


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


def insert_usage(
    session_id: Optional[str],
    chat_id: int,
    thread_id: Optional[int],
    provider: str,
    model_name: str,
    role: str,
    usage: Dict[str, Any] | None,
    meta: Dict[str, Any] | None = None,
) -> bool:
    """Insert token usage row. Returns False when DATABASE_URL missing or on error."""
    db_url = _get_db_url()
    if not db_url or not usage:
        return False
    try:
        # Normalize token keys from different providers
        def _get_int(d: Dict[str, Any], *keys: str) -> int:
            for k in keys:
                if k in d and d[k] is not None:
                    try:
                        return int(d[k])
                    except Exception:
                        pass
            return 0

        pt = _get_int(usage, "prompt_tokens", "prompt_token_count", "input_tokens")
        ct = _get_int(usage, "completion_tokens", "candidates_token_count", "output_tokens")
        tt = _get_int(usage, "total_tokens", "total_token_count")
        if tt == 0:
            tt = pt + ct

        # Meta stores raw usage data if provided
        meta_payload: Dict[str, Any] = meta.copy() if meta else {}
        # Put raw usage under 'raw'
        if "raw" in usage:
            meta_payload["raw"] = usage["raw"]
        else:
            meta_payload["raw"] = usage

        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into llm_usage (
                        session_id, chat_id, thread_id, provider, model_name, role,
                        prompt_tokens, completion_tokens, total_tokens, meta
                    ) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        session_id,
                        chat_id,
                        thread_id,
                        provider,
                        model_name,
                        role,
                        pt,
                        ct,
                        tt,
                        psycopg.types.json.Json(meta_payload),
                    ),
                )
            conn.commit()
        return True
    except Exception:
        return False


def get_usage_summary(chat_id: int, hours: int = 24, thread_id: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
    """Aggregate usage by provider/model in the last N hours. Returns list of dicts or None."""
    db_url = _get_db_url()
    if not db_url:
        return None
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                if thread_id is not None:
                    cur.execute(
                        """
                        select provider, model_name,
                               coalesce(sum(prompt_tokens),0) as prompt_tokens,
                               coalesce(sum(completion_tokens),0) as completion_tokens,
                               coalesce(sum(total_tokens),0) as total_tokens
                        from llm_usage
                        where chat_id = %s
                          and thread_id = %s
                          and created_at > now() - make_interval(hours => %s)
                        group by provider, model_name
                        order by total_tokens desc
                        """,
                        (chat_id, thread_id, hours),
                    )
                else:
                    cur.execute(
                        """
                        select provider, model_name,
                               coalesce(sum(prompt_tokens),0) as prompt_tokens,
                               coalesce(sum(completion_tokens),0) as completion_tokens,
                               coalesce(sum(total_tokens),0) as total_tokens
                        from llm_usage
                        where chat_id = %s
                          and created_at > now() - make_interval(hours => %s)
                        group by provider, model_name
                        order by total_tokens desc
                        """,
                        (chat_id, hours),
                    )
                rows = cur.fetchall()
        result: List[Dict[str, Any]] = []
        for r in rows:
            result.append(
                {
                    "provider": r[0],
                    "model_name": r[1],
                    "prompt_tokens": int(r[2] or 0),
                    "completion_tokens": int(r[3] or 0),
                    "total_tokens": int(r[4] or 0),
                }
            )
        return result
    except Exception:
        return None


def ensure_topic(title: str, description: Optional[str] = None, tags: Optional[List[str]] = None) -> bool:
    """Ensure a topic with the given title exists. Returns True if exists or created.
    If DATABASE_URL is missing, returns False (no-op).
    """
    db_url = _get_db_url()
    if not db_url:
        return False
    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("select id from topics where title = %s limit 1", (title,))
                row = cur.fetchone()
                if row:
                    return True
                # Insert minimal fields; description/tags optional
                cur.execute(
                    "insert into topics (title, description, tags) values (%s, %s, %s)",
                    (title, description, tags),
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
