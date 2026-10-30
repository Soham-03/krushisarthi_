"""Tiny SQLite layer. Good enough for a hackathon; swap for Postgres later."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import settings

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS farms(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, name TEXT NOT NULL, crop TEXT NOT NULL,
  sowing_date TEXT NOT NULL, geojson TEXT NOT NULL, lat REAL, lng REAL, area_ha REAL,
  scenario TEXT DEFAULT 'healthy', reminder_day INTEGER DEFAULT 6, created_at TEXT);
CREATE TABLE IF NOT EXISTS soil(farm_id INTEGER PRIMARY KEY, data TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS series_cache(farm_id INTEGER PRIMARY KEY, data TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS weather_cache(farm_id INTEGER PRIMARY KEY, data TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS checkups(
  id INTEGER PRIMARY KEY AUTOINCREMENT, farm_id INTEGER NOT NULL, user_id TEXT NOT NULL, week_start TEXT,
  target INTEGER, spots TEXT, status TEXT DEFAULT 'active', summary TEXT, created_at TEXT, completed_at TEXT);
CREATE TABLE IF NOT EXISTS checkup_photos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, checkup_id INTEGER NOT NULL, spot_index INTEGER NOT NULL, path TEXT,
  lat REAL, lng REAL, result TEXT, created_at TEXT, UNIQUE(checkup_id, spot_index));
CREATE TABLE IF NOT EXISTS detections(
  id INTEGER PRIMARY KEY AUTOINCREMENT, farm_id INTEGER, user_id TEXT, path TEXT, result TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, farm_id INTEGER, kind TEXT, level TEXT,
  title TEXT, body TEXT, data TEXT, dedupe_key TEXT, read INTEGER DEFAULT 0, created_at TEXT,
  UNIQUE(user_id, dedupe_key));
CREATE TABLE IF NOT EXISTS kb_documents(
  id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, publisher TEXT, url TEXT, published TEXT,
  language TEXT DEFAULT 'en', crops TEXT, source_type TEXT, license_note TEXT, content_hash TEXT UNIQUE, added_at TEXT);
CREATE TABLE IF NOT EXISTS kb_chunks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id INTEGER NOT NULL, idx INTEGER, page INTEGER, text TEXT NOT NULL, embedding BLOB);
CREATE INDEX IF NOT EXISTS kb_chunks_doc ON kb_chunks(doc_id);
CREATE TABLE IF NOT EXISTS push_subs(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, endpoint TEXT UNIQUE, sub TEXT, created_at TEXT);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def conn():
    c = sqlite3.connect(settings.db_path, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db():
    with _lock, conn() as c:
        c.executescript(SCHEMA)
        try:  # keyword search index for the knowledge base
            c.execute("CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(text, title, tokenize='unicode61 remove_diacritics 2')")
        except sqlite3.OperationalError:
            pass  # SQLite without FTS5: the knowledge base reports itself as unavailable


def q(sql: str, args=()):
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql: str, args=()):
    rows = q(sql, args)
    return rows[0] if rows else None


def run(sql: str, args=()) -> int:
    with _lock, conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(s, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except Exception:
        return default
