from __future__ import annotations

import psycopg


def apply_migration(database_url: str, sql_file_path: str) -> None:
    """Apply a SQL migration file to the target Postgres database."""
    with open(sql_file_path, "r", encoding="utf-8") as f:
        sql = f.read()

    # psycopg3 auto-commits only when explicitly asked
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
