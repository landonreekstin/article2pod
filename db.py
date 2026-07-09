# ~/nixos-config/modules/nixos/homelab/article2pod-src/db.py
import sqlite3
import os
import uuid
import secrets
from datetime import datetime, timezone
from contextlib import contextmanager

DB_PATH = os.environ.get("ARTICLE2POD_DB", "/var/lib/article2pod/db.sqlite")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(admin_token: str = "", default_voice: str = "af_heart"):
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT    NOT NULL UNIQUE,
                token      TEXT    NOT NULL UNIQUE,
                voice      TEXT    NOT NULL DEFAULT 'af_heart',
                created_at TEXT    NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guid        TEXT    NOT NULL UNIQUE,
                url         TEXT    NOT NULL UNIQUE,
                title       TEXT,
                author      TEXT,
                pub_date    TEXT,
                status      TEXT    NOT NULL DEFAULT 'queued',
                duration    INTEGER,
                size_bytes  INTEGER,
                added_at    TEXT    NOT NULL,
                processed_at TEXT,
                error       TEXT,
                user_id     INTEGER REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Migrations: add columns to existing DB if missing
        cols = {row[1] for row in conn.execute("PRAGMA table_info(articles)")}
        if "user_id" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN user_id INTEGER REFERENCES users(id)")
        if "voice" not in cols:
            conn.execute("ALTER TABLE articles ADD COLUMN voice TEXT")

        # Bootstrap lando (admin) user if admin_token is provided
        if admin_token:
            now = datetime.now(timezone.utc).isoformat()
            conn.execute(
                "INSERT OR IGNORE INTO users (username, token, voice, created_at) VALUES (?, ?, ?, ?)",
                ("lando", admin_token, default_voice, now),
            )
            # Migrate any orphaned articles to lando
            row = conn.execute("SELECT id FROM users WHERE token = ?", (admin_token,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE articles SET user_id = ? WHERE user_id IS NULL",
                    (row["id"],),
                )


def get_user_by_token(token: str) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()


def get_user_by_id(user_id: int) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_all_users() -> list[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()


def create_user(username: str, voice: str = "af_heart") -> sqlite3.Row:
    token = secrets.token_hex(32)
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO users (username, token, voice, created_at) VALUES (?, ?, ?, ?)",
            (username, token, voice, now),
        )
        return conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()


def delete_user(user_id: int) -> list[str]:
    """Delete a user and their articles. Returns list of guids whose MP3s should be removed."""
    with get_db() as conn:
        guids = [
            r["guid"]
            for r in conn.execute(
                "SELECT guid FROM articles WHERE user_id = ?", (user_id,)
            ).fetchall()
        ]
        conn.execute("DELETE FROM articles WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return guids


def requeue_article(guid: str, user_id: int, voice: str) -> bool:
    """Reset article to queued with a specific voice. Returns True if found and owned."""
    with get_db() as conn:
        result = conn.execute(
            """UPDATE articles
               SET status='queued', voice=?, error=NULL,
                   duration=NULL, size_bytes=NULL, processed_at=NULL
               WHERE guid=? AND user_id=?""",
            (voice, guid, user_id),
        )
        return result.rowcount > 0


def get_user_voice(user_id: int, fallback: str = "af_heart") -> str:
    with get_db() as conn:
        row = conn.execute("SELECT voice FROM users WHERE id = ?", (user_id,)).fetchone()
        return row["voice"] if row else fallback


def set_user_voice(user_id: int, voice: str) -> None:
    with get_db() as conn:
        conn.execute("UPDATE users SET voice = ? WHERE id = ?", (voice, user_id))


def enqueue(url: str, user_id: int) -> dict | None:
    """Insert a new article URL for a user. Returns the row dict or None if already exists."""
    guid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO articles (guid, url, added_at, user_id) VALUES (?, ?, ?, ?)",
                (guid, url, now, user_id),
            )
        return {"guid": guid, "url": url, "status": "queued", "added_at": now}
    except sqlite3.IntegrityError:
        return None  # already queued


def get_next_queued() -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM articles WHERE status = 'queued' ORDER BY added_at LIMIT 1"
        ).fetchone()


def mark_processing(article_id: int):
    with get_db() as conn:
        conn.execute(
            "UPDATE articles SET status = 'processing' WHERE id = ?",
            (article_id,),
        )


def mark_done(article_id: int, title: str, author: str, pub_date: str,
              duration: int, size_bytes: int):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """UPDATE articles
               SET status='done', title=?, author=?, pub_date=?,
                   duration=?, size_bytes=?, processed_at=?, error=NULL
               WHERE id=?""",
            (title, author, pub_date, duration, size_bytes, now, article_id),
        )


def mark_failed(article_id: int, error: str):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            "UPDATE articles SET status='failed', error=?, processed_at=? WHERE id=?",
            (error[:2000], now, article_id),
        )


def get_all(user_id: int | None = None) -> list[sqlite3.Row]:
    with get_db() as conn:
        if user_id is not None:
            return conn.execute(
                "SELECT * FROM articles WHERE user_id = ? ORDER BY added_at DESC",
                (user_id,),
            ).fetchall()
        return conn.execute(
            """SELECT a.*, u.username
               FROM articles a LEFT JOIN users u ON a.user_id = u.id
               ORDER BY a.added_at DESC"""
        ).fetchall()


def get_article_by_guid(guid: str) -> sqlite3.Row | None:
    with get_db() as conn:
        return conn.execute("SELECT * FROM articles WHERE guid = ?", (guid,)).fetchone()


def delete_article(guid: str, user_id: int | None = None) -> bool:
    """Delete an article. If user_id provided, only deletes if article belongs to that user."""
    with get_db() as conn:
        if user_id is not None:
            result = conn.execute(
                "DELETE FROM articles WHERE guid = ? AND user_id = ?", (guid, user_id)
            )
        else:
            result = conn.execute("DELETE FROM articles WHERE guid = ?", (guid,))
        return result.rowcount > 0


def get_setting(key: str, default: str = "") -> str:
    with get_db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_done(user_id: int | None = None) -> list[sqlite3.Row]:
    with get_db() as conn:
        if user_id is not None:
            return conn.execute(
                "SELECT * FROM articles WHERE status='done' AND user_id = ? ORDER BY processed_at DESC",
                (user_id,),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM articles WHERE status='done' ORDER BY processed_at DESC"
        ).fetchall()
