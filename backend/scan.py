"""Bibliothek einlesen und Bilder prüfen – im Hintergrund, mit Fortschrittsanzeige.

1. Metadaten aller Fotos und Videos aus Immich lesen (Seite für Seite, 1000 pro Anfrage)
2. Welche sind in keinem Album? (eigene Suche)
3. Duplikat-Gruppen von Immich holen
4. Neue Fotos prüfen: Vorschaubild laden und Schärfe/Helligkeit/Fingerabdruck berechnen
   (nur einmal je Foto – beim nächsten Einlesen kommen nur neue dazu)
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import logging
import os
import threading
import time
from datetime import datetime

from . import analyze, db, store, thumbs
from .immich import Immich, ImmichError, duration_ms

log = logging.getLogger("immichhelper.scan")
WORKERS = int(os.environ.get("IH_ANALYZE_WORKERS", "4"))


class Job:
    def __init__(self, owner: str):
        self.owner = owner
        self.state = "running"
        self.phase = "library"
        self.done = 0
        self.total = 0
        self.message = "Bibliothek wird gelesen …"
        self.started = time.time()
        self.finished: float | None = None
        self.error: str | None = None
        self.cancel = False
        self.analyzed = 0

    def public(self) -> dict:
        return {"state": self.state, "phase": self.phase, "done": self.done, "total": self.total, "message": self.message,
                "started": self.started, "finished": self.finished, "error": self.error, "analyzed": self.analyzed}


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def job(owner: str) -> Job | None:
    return _jobs.get(owner)


def client_for(session) -> Immich:
    base = store.immich_url()
    if session["kind"] == "key":
        return Immich(base, api_key=session["secret"])
    return Immich(base, token=session["secret"])


def start(owner: str, session, *, analysis: bool = True) -> Job:
    with _lock:
        j = _jobs.get(owner)
        if j and j.state == "running":
            return j
        j = Job(owner)
        _jobs[owner] = j
    cli = client_for(session)
    secret = session["secret"]

    def worker():
        try:
            sync(owner, cli, j)
            if analysis and not j.cancel:
                analyze_missing(owner, cli, j)
            j.state = "done"
            j.message = "Fertig"
            db.run("UPDATE user_meta SET sync_error=NULL WHERE owner=?", (owner,))
        except ImmichError as e:
            j.state = "error"
            j.error = e.message
            if e.status == 401:
                j.error = "Die Anmeldung bei Immich ist abgelaufen. Bitte neu anmelden."
                db.session_invalidate_secret(secret)
            db.run("UPDATE user_meta SET sync_error=? WHERE owner=?", (j.error, owner))
        except Exception as e:  # noqa: BLE001
            log.exception("Einlesen fehlgeschlagen")
            j.state = "error"
            j.error = f"Unerwarteter Fehler: {e}"
            db.run("UPDATE user_meta SET sync_error=? WHERE owner=?", (j.error, owner))
        finally:
            j.finished = time.time()
            db.bump(owner)

    threading.Thread(target=worker, daemon=True, name=f"sync-{owner[:8]}").start()
    return j


# ---------------------------------------------------------------------------
def _ts(v) -> float | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def row_from_asset(owner: str, a: dict, now: float) -> tuple:
    ex = a.get("exifInfo") or {}
    stack = a.get("stack") or {}
    vis = a.get("visibility")
    archived = vis == "archive" if vis else bool(a.get("isArchived"))
    w = ex.get("exifImageWidth") or a.get("width")
    h = ex.get("exifImageHeight") or a.get("height")
    if ex.get("orientation") in ("5", "6", "7", "8", 5, 6, 7, 8) and w and h:
        w, h = h, w
    return (owner, a["id"], a.get("type"), a.get("originalFileName"), a.get("originalPath"),
            _ts(a.get("fileCreatedAt")) or _ts(a.get("localDateTime")) or _ts(a.get("createdAt")), a.get("localDateTime"),
            ex.get("fileSizeInByte"), w, h, ex.get("make"), ex.get("model"), ex.get("lensModel"),
            ex.get("city"), ex.get("state"), ex.get("country"), ex.get("latitude"), ex.get("longitude"),
            duration_ms(a.get("duration")), int(bool(a.get("isFavorite"))), int(archived), a.get("duplicateId"),
            a.get("livePhotoVideoId"), stack.get("id"),
            (1 if stack.get("primaryAssetId") == a["id"] else 0) if stack else None,
            a.get("checksum"), a.get("originalMimeType"), now)


UPSERT = """
INSERT INTO assets (owner,id,type,name,path,taken,local,size,w,h,make,model,lens,city,state,country,lat,lon,dur,fav,archived,
                    dup,live,stack,stack_primary,checksum,mime,seen,trashed,gone)
VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,NULL)
ON CONFLICT(owner,id) DO UPDATE SET type=excluded.type, name=excluded.name, path=excluded.path, taken=excluded.taken,
  local=excluded.local, size=excluded.size, w=excluded.w, h=excluded.h, make=excluded.make, model=excluded.model,
  lens=excluded.lens, city=excluded.city, state=excluded.state, country=excluded.country, lat=excluded.lat, lon=excluded.lon,
  dur=excluded.dur, fav=excluded.fav, archived=excluded.archived, dup=excluded.dup, live=excluded.live, stack=excluded.stack,
  stack_primary=excluded.stack_primary, checksum=excluded.checksum, mime=excluded.mime, seen=excluded.seen, trashed=0, gone=NULL
"""


def _search(cli: Immich, archived: bool, extra: dict | None = None, with_exif: bool = True):
    """Neuere Immich-Versionen kennen „visibility“, ältere nur „isArchived“."""
    try:
        yield from cli.search_all({"visibility": "archive" if archived else "timeline", "withStacked": True, **(extra or {})},
                                  with_exif=with_exif)
    except ImmichError as e:
        if e.status != 400:
            raise
        yield from cli.search_all({"isArchived": archived, **(extra or {})}, with_exif=with_exif)


def sync(owner: str, cli: Immich, j: Job) -> None:
    now = time.time()
    j.phase, j.message = "library", "Bibliothek wird gelesen …"
    try:
        stats = cli.statistics()
        j.total = int(stats.get("total") or 0)
    except ImmichError as e:
        if e.status == 401:
            raise
        j.total = 0
    seen: set[str] = set()
    for archived in (False, True):
        for items in _search(cli, archived):
            rows = [row_from_asset(owner, a, now) for a in items if a.get("id")]
            seen.update(r[1] for r in rows)
            if rows:
                db.many(UPSERT, rows)
            j.done = len(seen)
            j.total = max(j.total, j.done)
            if j.cancel:
                return
    # Was in Immich nicht mehr auftaucht, ist dort gelöscht (oder im Papierkorb)
    db.run("UPDATE assets SET gone=? WHERE owner=? AND seen < ? AND gone IS NULL", (now, owner, now - 1))
    db.run("DELETE FROM assets WHERE owner=? AND gone IS NOT NULL AND gone < ?", (owner, now - 180 * 86400))
    db.run("DELETE FROM decisions WHERE owner=? AND committed=1 AND id NOT IN (SELECT id FROM assets WHERE owner=?)", (owner, owner))
    # In Immich wiederhergestellt → wieder ganz normal behandeln
    db.run("""DELETE FROM decisions WHERE owner=? AND committed=1 AND decision='trash'
              AND id IN (SELECT id FROM assets WHERE owner=? AND seen >= ?)""", (owner, owner, now))

    j.phase, j.message = "albums", "Alben werden abgeglichen …"
    not_in_album: set[str] = set()
    try:
        for archived in (False, True):
            for items in _search(cli, archived, {"isNotInAlbum": True}, with_exif=False):
                not_in_album.update(a["id"] for a in items if a.get("id"))
        db.run("UPDATE assets SET in_album=1 WHERE owner=?", (owner,))
        db.many("UPDATE assets SET in_album=0 WHERE owner=? AND id=?", [(owner, i) for i in not_in_album])
    except ImmichError as e:
        if e.status == 401:
            raise
        log.warning("Album-Abgleich nicht möglich: %s", e.message)

    j.phase, j.message = "duplicates", "Duplikate werden abgefragt …"
    try:
        groups = cli.duplicates()
        rows, dups = [], []
        for g in groups:
            did = g.get("duplicateId")
            if not did:
                continue
            ids = [a["id"] for a in g.get("assets") or [] if a.get("id")]
            rows.append((owner, did, json.dumps(g.get("suggestedKeepAssetIds") or [])))
            dups.extend((did, owner, i) for i in ids)
        db.run("DELETE FROM dupgroups WHERE owner=?", (owner,))
        db.run("UPDATE assets SET dup=NULL WHERE owner=?", (owner,))
        if rows:
            db.many("INSERT OR REPLACE INTO dupgroups (owner, dup_id, suggested) VALUES (?,?,?)", rows)
            db.many("UPDATE assets SET dup=? WHERE owner=? AND id=?", dups)
    except ImmichError as e:
        if e.status == 401:
            raise
        log.warning("Duplikate nicht abrufbar: %s", e.message)

    db.run("INSERT OR IGNORE INTO user_meta (owner) VALUES (?)", (owner,))
    db.run("UPDATE user_meta SET last_sync=? WHERE owner=?", (time.time(), owner))
    db.bump(owner)


def analyze_missing(owner: str, cli: Immich, j: Job) -> None:
    rows = db.q("""SELECT a.id, a.checksum FROM assets a LEFT JOIN analysis n ON n.id = a.id
                   WHERE a.owner=? AND a.type='IMAGE' AND a.trashed=0 AND a.gone IS NULL
                     AND (n.id IS NULL OR IFNULL(n.checksum,'') != IFNULL(a.checksum,'') OR (n.hi IS NULL AND n.err IS NULL))
                   ORDER BY a.taken DESC""", (owner,))
    j.phase = "analysis"
    j.total = len(rows)
    j.done = 0
    j.message = "Fotos werden geprüft …" if rows else "Alle Fotos sind schon geprüft."
    if not rows:
        return

    def one(r):
        if j.cancel:
            return None
        thumbs.wait_for_quiet()  # wer gerade Bilder ansieht, hat Vorrang
        try:
            data, ctype = thumbs.fetch(cli, r["id"], "preview")
            thumbs.remember(r["id"], "preview", r["checksum"], data, ctype)
            res = analyze.analyze(data)
            return (r["id"], r["checksum"], res["sharp"], res["sharp_g"], res["bright"], res["contrast"], res["dhash"], time.time(), None, res["hi"])
        except ImmichError as e:
            if e.status == 401:
                raise
            return (r["id"], r["checksum"], None, None, None, None, None, time.time(), e.message[:200], None)
        except Exception as e:  # noqa: BLE001 – kaputtes Vorschaubild o. ä.
            return (r["id"], r["checksum"], None, None, None, None, None, time.time(), str(e)[:200], None)

    sql = "INSERT OR REPLACE INTO analysis (id, checksum, sharp, sharp_g, bright, contrast, dhash, ts, err, hi) VALUES (?,?,?,?,?,?,?,?,?,?)"
    buf: list[tuple] = []
    last_bump = time.time()
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for res in ex.map(one, rows):
            j.done += 1
            if res:
                buf.append(res)
                if res[2] is not None:
                    j.analyzed += 1
            if len(buf) >= 50:
                db.many(sql, buf)
                buf = []
                if time.time() - last_bump > 20:
                    db.bump(owner)
                    last_bump = time.time()
            if j.cancel:
                break
    if buf:
        db.many(sql, buf)


# ---------------------------------------------------------------------------
# Regelmäßig im Hintergrund
# ---------------------------------------------------------------------------
def start_background() -> None:
    def loop():
        time.sleep(90)
        while True:
            try:
                for s in db.sessions_for_background():
                    owner = s["user_id"]
                    hours = db.user_settings(owner).get("auto_sync_hours", 12)
                    if not hours:
                        continue
                    m = db.meta(owner)
                    last = (m["last_sync"] if m else None) or 0
                    j = _jobs.get(owner)
                    if (not j or j.state != "running") and time.time() - last > hours * 3600 and store.immich_url():
                        log.info("Lese Bibliothek von %s neu ein", s["name"])
                        start(owner, s)
            except Exception as e:  # noqa: BLE001
                log.warning("Hintergrund-Aktualisierung: %s", e)
            time.sleep(900)
    threading.Thread(target=loop, daemon=True, name="autosync").start()
