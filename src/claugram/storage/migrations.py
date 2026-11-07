"""Schema migrations for the claugram state DB."""

from __future__ import annotations

import sqlite3

SCHEMA = [
    # v1 -- initial schema
    """
    CREATE TABLE IF NOT EXISTS projects (
        id          TEXT PRIMARY KEY,
        name        TEXT,
        root_path   TEXT UNIQUE,
        created_at  TEXT
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id                    TEXT PRIMARY KEY,
        project_id            TEXT,
        claude_session_id     TEXT,
        last_transcript_path  TEXT,
        last_activity_at      TEXT,
        status                TEXT
    );

    CREATE TABLE IF NOT EXISTS pending_questions (
        id                   TEXT PRIMARY KEY,
        project_id           TEXT,
        session_id           TEXT,
        chat_id              INTEGER,
        telegram_message_id  INTEGER,
        question             TEXT,
        options_json         TEXT,
        status               TEXT,
        answer_text          TEXT,
        answered_by          INTEGER,
        answered_at          TEXT,
        created_at           TEXT,
        expires_at           TEXT
    );

    CREATE TABLE IF NOT EXISTS pending_permissions (
        id                   TEXT PRIMARY KEY,
        project_id           TEXT,
        session_id           TEXT,
        chat_id              INTEGER,
        telegram_message_id  INTEGER,
        tool_name            TEXT,
        tool_input_json      TEXT,
        risk_level           TEXT,
        reason               TEXT,
        status               TEXT,
        decision             TEXT,
        decided_by           INTEGER,
        decided_at           TEXT,
        created_at           TEXT,
        expires_at           TEXT
    );

    CREATE TABLE IF NOT EXISTS audit_events (
        id          TEXT PRIMARY KEY,
        project_id  TEXT,
        session_id  TEXT,
        event_type  TEXT,
        payload_json TEXT,
        created_at  TEXT
    );

    CREATE TABLE IF NOT EXISTS controller_jobs (
        id          TEXT PRIMARY KEY,
        project_id  TEXT,
        chat_id     INTEGER,
        command     TEXT,
        prompt      TEXT,
        status      TEXT,
        result      TEXT,
        created_at  TEXT,
        updated_at  TEXT
    );

    CREATE TABLE IF NOT EXISTS kv (
        key    TEXT PRIMARY KEY,
        value  TEXT
    );
    """,
]


def apply_migrations(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA user_version")
    current = cur.fetchone()[0]
    for version in range(current, len(SCHEMA)):
        conn.executescript(SCHEMA[version])
        conn.execute(f"PRAGMA user_version = {version + 1}")
    conn.commit()
