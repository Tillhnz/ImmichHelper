"""Lokale Datenbank (SQLite) unter IH_STATE_DIR.

Hier liegt nur eine Kopie der Metadaten aus Immich (zum schnellen Sortieren und Gruppieren),
die Ergebnisse der Bildanalyse (Schärfe, Helligkeit, Ähnlichkeit) und was du entschieden hast
(behalten, aussortieren). Die Fotos selbst bleiben in Immich.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

STATE_DIR = Path(os.environ.get("IH_STATE_DIR", "/var/lib/immichhelper"))
DB_FILE = STATE_DIR / "immichhelper.db"

_local = threading.local()
_init_lock = threading.Lock()
_initialized: set[str] = set()
_version: dict[str, int] = {}  # owner → Zähler, ändert sich bei jeder Änderung (für Zwischenspeicher)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  sid TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT, email TEXT, is_admin INTEGER DEFAULT 0,
  kind TEXT NOT NULL, secret TEXT NOT NULL, created REAL, last_seen REAL, expires REAL
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS assets (
  owner TEXT NOT NULL, id TEXT NOT NULL, type TEXT, name TEXT, path TEXT, taken REAL, local TEXT,
  size INTEGER, w INTEGER, h INTEGER, make TEXT, model TEXT, lens TEXT, city TEXT, state TEXT, country TEXT,
  lat REAL, lon REAL, dur INTEGER, fav INTEGER DEFAULT 0, archived INTEGER DEFAULT 0, dup TEXT, live TEXT,
  stack TEXT, stack_primary INTEGER, checksum TEXT, mime TEXT, in_album INTEGER DEFAULT 1,
  trashed INTEGER DEFAULT 0, gone REAL, seen REAL,
  PRIMARY KEY (owner, id)
);
CREATE INDEX IF NOT EXISTS assets_taken ON assets(owner, taken);

CREATE TABLE IF NOT EXISTS analysis (
  id TEXT PRIMARY KEY, checksum TEXT, sharp REAL, sharp_g REAL, bright REAL, contrast REAL, dhash INTEGER,
  ts REAL, err TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
  owner TEXT NOT NULL, id TEXT NOT NULL, decision TEXT NOT NULL, ts REAL, committed INTEGER DEFAULT 0,
  PRIMARY KEY (owner, id)
);

CREATE TABLE IF NOT EXISTS log (
  lid INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT NOT NULL, ts REAL, kind TEXT, label TEXT, ids TEXT,
  count INTEGER, bytes INTEGER, restored REAL
);
CREATE INDEX IF NOT EXISTS log_owner ON log(owner, ts);

CREATE TABLE IF NOT EXISTS dupgroups (
  owner TEXT NOT NULL, dup_id TEXT NOT NULL, suggested TEXT, PRIMARY KEY (owner, dup_id)
);

CREATE TABLE IF NOT EXISTS user_meta (
  owner TEXT PRIMARY KEY, name TEXT, settings TEXT, last_sync REAL, sync_error TEXT
);
"""


def conn() -> sqlite3.Connection:
    path = str(DB_FILE)
    c = getattr(_local, "conn", None)
    if c is not None and getattr(_local, "path", None) == path:
        return c
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA foreign_keys=OFF")
    with _init_lock:
        if path not in _initialized:
            c.executescript(SCHEMA)
            cols = {r[1] for r in c.execute("PRAGMA table_info(analysis)")}
            if "hi" not in cols:
                c.execute("ALTER TABLE analysis ADD COLUMN hi REAL")
            _initialized.add(path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
    _local.conn = c
    _local.path = path
    return c


def q(sql: str, args=()) -> list[sqlite3.Row]:
    return conn().execute(sql, args).fetchall()


def q1(sql: str, args=()) -> sqlite3.Row | None:
    return conn().execute(sql, args).fetchone()


def run(sql: str, args=()) -> int:
    cur = conn().execute(sql, args)
    return cur.rowcount


def many(sql: str, rows) -> None:
    c = conn()
    c.execute("BEGIN")
    try:
        c.executemany(sql, rows)
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise


def bump(owner: str) -> None:
    _version[owner] = _version.get(owner, 0) + 1


def version(owner: str) -> int:
    return _version.get(owner, 0)


# ---------------------------------------------------------------------------
# Sitzungen
# ---------------------------------------------------------------------------
def session_get(sid: str | None) -> sqlite3.Row | None:
    if not sid or len(sid) > 100:
        return None
    r = q1("SELECT * FROM sessions WHERE sid=?", (sid,))
    if not r:
        return None
    if r["expires"] and r["expires"] < time.time():
        run("DELETE FROM sessions WHERE sid=?", (sid,))
        return None
    if time.time() - (r["last_seen"] or 0) > 300:
        run("UPDATE sessions SET last_seen=? WHERE sid=?", (time.time(), sid))
    return r


def session_save(sid: str, *, user_id: str, name: str, email: str, is_admin: bool, kind: str, secret: str, days: int) -> None:
    now = time.time()
    run("INSERT OR REPLACE INTO sessions (sid,user_id,name,email,is_admin,kind,secret,created,last_seen,expires) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (sid, user_id, name, email, int(is_admin), kind, secret, now, now, now + days * 86400))
    run("INSERT OR IGNORE INTO user_meta (owner, name) VALUES (?, ?)", (user_id, name))
    run("UPDATE user_meta SET name=? WHERE owner=?", (name, user_id))


def session_delete(sid: str) -> None:
    run("DELETE FROM sessions WHERE sid=?", (sid,))


def session_invalidate_secret(secret: str) -> None:
    """Immich hat den Zugang abgelehnt (abgemeldet, Schlüssel gelöscht) → alle Sitzungen damit beenden."""
    run("DELETE FROM sessions WHERE secret=?", (secret,))


def sessions_for_background() -> list[sqlite3.Row]:
    """Je Benutzer der zuletzt benutzte, noch gültige Zugang (für Aktualisierungen im Hintergrund)."""
    rows = q("SELECT * FROM sessions WHERE expires > ? ORDER BY last_seen DESC", (time.time(),))
    out, seen = [], set()
    for r in rows:
        if r["user_id"] not in seen:
            seen.add(r["user_id"])
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Benutzer-Einstellungen
# ---------------------------------------------------------------------------
DEFAULTS = {
    "burst_seconds": 4,        # Serien: höchstens so viele Sekunden zwischen zwei Fotos
    "burst_similarity": 14,    # Serien: max. Unterschied im Bild-Fingerabdruck (0–64)
    "blur_threshold": 35,      # Unscharf: unter diesem Schärfewert
    "short_video_s": 3,        # Kurze Videos: kürzer als … Sekunden
    "large_mb": 200,           # Große Dateien: ab … MB
    "event_min": 15,           # Ereignisse: mindestens … Fotos
    "raw_follow": True,        # Beim Löschen eines JPGs die zugehörige RAW-Datei mitlöschen
    "include_archived": True,  # Archivierte Fotos mit aufräumen
    "include_favorites": False,  # Favoriten in Vorschlägen zeigen (Standard: nie Favoriten vorschlagen)
    "auto_sync_hours": 12,     # Bibliothek alle … Stunden im Hintergrund neu einlesen (0 = aus)
    "swipe_order": "new",      # Wischen: neueste oder älteste zuerst
}


def user_settings(owner: str) -> dict:
    r = q1("SELECT settings FROM user_meta WHERE owner=?", (owner,))
    data = {}
    if r and r["settings"]:
        try:
            data = json.loads(r["settings"])
        except ValueError:
            data = {}
    return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}


def set_user_settings(owner: str, values: dict) -> dict:
    cur = user_settings(owner)
    for k, v in values.items():
        if k not in DEFAULTS:
            continue
        d = DEFAULTS[k]
        if isinstance(d, bool):
            cur[k] = bool(v)
        elif isinstance(d, int):
            try:
                cur[k] = int(float(v))
            except (TypeError, ValueError):
                pass
        elif isinstance(d, str):
            cur[k] = str(v)[:40]
    run("INSERT OR IGNORE INTO user_meta (owner) VALUES (?)", (owner,))
    run("UPDATE user_meta SET settings=? WHERE owner=?", (json.dumps(cur), owner))
    return cur


def meta(owner: str) -> sqlite3.Row | None:
    return q1("SELECT * FROM user_meta WHERE owner=?", (owner,))


def add_log(owner: str, kind: str, label: str, ids: list[str], nbytes: int = 0) -> int:
    cur = conn().execute("INSERT INTO log (owner, ts, kind, label, ids, count, bytes) VALUES (?,?,?,?,?,?,?)",
                         (owner, time.time(), kind, label, json.dumps(ids), len(ids), int(nbytes or 0)))
    return int(cur.lastrowid)
