"""ImmichHelper – Fotos in Immich aussortieren und ordnen. Starlette-App (API + Oberfläche)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import db, scan, store, suggest, thumbs, updatewatch
from .immich import Immich, ImmichError, is_uuid, normalize_url

BASE = Path(__file__).resolve().parent.parent
FRONTEND = BASE / "frontend"
VERSION = (BASE / "VERSION").read_text().strip() if (BASE / "VERSION").exists() else "dev"
REPO = os.environ.get("IH_REPO", "Tillhnz/ImmichHelper")
COOKIE = "ih_session"
MAX_IDS = 50000

logging.basicConfig(level=os.environ.get("IH_LOG_LEVEL", "WARNING"))


# Getrennte Arbeits-Threads: Bilder/Videos/Immich-Anfragen warten meist nur auf das Netz (viele Threads, billig),
# die Berechnung der Vorschläge braucht Rechenzeit (wenige Threads). So blockiert das eine nie das andere.
IO_POOL = ThreadPoolExecutor(max_workers=int(os.environ.get("IH_IO_THREADS", "48")), thread_name_prefix="io")
CPU_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lib")


async def run_io(fn, *args, **kw):
    return await asyncio.get_running_loop().run_in_executor(IO_POOL, partial(fn, *args, **kw))


async def run_cpu(fn, *args, **kw):
    return await asyncio.get_running_loop().run_in_executor(CPU_POOL, partial(fn, *args, **kw))


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message


def err(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


async def body_json(request: Request) -> dict:
    try:
        data = await request.json()
    except (ValueError, UnicodeDecodeError):
        raise ApiError(400, "Ungültige Anfrage")
    if not isinstance(data, dict):
        raise ApiError(400, "Ungültige Anfrage")
    return data


def ids_from(data, key: str = "ids") -> list[str]:
    v = data.get(key) if isinstance(data, dict) else data
    if not isinstance(v, list) or len(v) > MAX_IDS:
        raise ApiError(400, "Ungültige Auswahl")
    out = [str(x) for x in v if is_uuid(x)]
    return list(dict.fromkeys(out))


def intq(request: Request, key: str, default: int, lo: int = 0, hi: int = 10 ** 9) -> int:
    try:
        return max(lo, min(hi, int(request.query_params.get(key, default))))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Sitzung → Immich-Zugang
# ---------------------------------------------------------------------------
class Ctx:
    def __init__(self, session):
        self.s = session
        self.owner = session["user_id"]
        self.admin = bool(session["is_admin"])
        self.cli = scan.client_for(session)

    async def call(self, fn, *args, **kw):
        """Immich im Hintergrund-Thread aufrufen; abgelaufene Anmeldung beendet die Sitzung."""
        try:
            return await run_io(fn, *args, **kw)
        except ImmichError as e:
            if e.status == 401:
                db.session_invalidate_secret(self.s["secret"])
                raise ApiError(401, "Deine Anmeldung bei Immich ist abgelaufen. Bitte neu anmelden.")
            raise ApiError(502 if e.status >= 500 else e.status, e.message)


def ctx(request: Request) -> Ctx:
    s = db.session_get(request.cookies.get(COOKIE))
    if not s:
        raise ApiError(401, "Bitte anmelden.")
    return Ctx(s)


def need_admin(request: Request) -> Ctx:
    c = ctx(request)
    if not c.admin:
        raise ApiError(403, "Nur für Immich-Administratoren.")
    return c


async def lib(c: Ctx) -> suggest.Library:
    return await run_cpu(suggest.library, c.owner)


# ---------------------------------------------------------------------------
# Einrichtung & Anmeldung
# ---------------------------------------------------------------------------
_fails: dict[str, list[float]] = {}


def _too_many(key: str) -> bool:
    now = time.time()
    arr = [t for t in _fails.get(key, []) if now - t < 900]
    _fails[key] = arr
    return len(arr) >= 10


async def setup_info(request: Request):
    url = store.immich_url()
    return JSONResponse({"configured": bool(url), "immich_url": url, "version": VERSION})


async def setup_save(request: Request):
    """Immich-Adresse festlegen: beim ersten Start ohne Anmeldung, danach nur für Admins."""
    if store.immich_url():
        need_admin(request)
    data = await body_json(request)
    url = normalize_url(str(data.get("url", "")))
    if not re.fullmatch(r"https?://[^\s/]+(/[^\s]*)?", url or ""):
        return err(400, "Bitte eine gültige Adresse angeben, z. B. http://192.168.1.20:2283")
    cli = Immich(url)
    if not await run_io(cli.ping):
        return err(400, f"Unter {url} antwortet kein Immich. Stimmt die Adresse (meist Port 2283)?")
    ver = await run_io(cli.server_version)
    store.set_setting("immich_url", url)
    if "public_url" in data:
        pub = normalize_url(str(data.get("public_url") or ""))
        if pub and not re.fullmatch(r"https?://[^\s/]+(/[^\s]*)?", pub):
            return err(400, "Ungültige Adresse für Links.")
        store.set_setting("immich_public_url", pub)
    return JSONResponse({"ok": True, "immich_url": url, "immich_version": ver})


async def login(request: Request):
    data = await body_json(request)
    base = store.immich_url()
    if not base:
        return err(409, "Zuerst die Adresse von Immich einstellen.")
    email = str(data.get("email", "")).strip()
    api_key = str(data.get("api_key", "")).strip()
    key = f"{client_ip(request)}|{(email or 'key').lower()}"
    if _too_many(key):
        return err(429, "Zu viele Fehlversuche. Bitte in 15 Minuten noch einmal probieren.")
    cli = Immich(base, api_key=api_key or None)
    try:
        if api_key:
            me = await run_io(cli.me)
            kind, secret = "key", api_key
        else:
            if not email or not data.get("password"):
                return err(400, "Bitte E-Mail und Passwort eingeben.")
            await run_io(cli.login, email, str(data.get("password")))
            me = await run_io(cli.me)
            kind, secret = "token", cli.token
    except ImmichError as e:
        if e.status in (400, 401, 403):
            _fails.setdefault(key, []).append(time.time())
            await asyncio.sleep(0.6)
            return err(401, "API-Schlüssel ungültig." if api_key else "E-Mail oder Passwort stimmt nicht (dieselben Daten wie bei Immich).")
        return err(502, e.message)
    _fails.pop(key, None)
    sid = secrets.token_urlsafe(32)
    remember = bool(data.get("remember", True))
    days = 30 if remember else 1
    db.session_save(sid, user_id=me["id"], name=me.get("name") or me.get("email"), email=me.get("email", ""),
                    is_admin=bool(me.get("isAdmin")), kind=kind, secret=secret, days=days)
    resp = JSONResponse({"ok": True})
    resp.set_cookie(COOKIE, sid, max_age=days * 86400 if remember else None, httponly=True, samesite="strict",
                    secure=request.url.scheme == "https", path="/")
    # Beim ersten Mal (oder wenn es lange her ist) gleich einlesen
    m = db.meta(me["id"])
    if not m or not m["last_sync"] or time.time() - m["last_sync"] > 6 * 3600:
        s = db.session_get(sid)
        if s:
            scan.start(me["id"], s)
    return resp


async def logout(request: Request):
    s = db.session_get(request.cookies.get(COOKIE))
    if s:
        db.session_delete(s["sid"])
        if s["kind"] == "token" and not db.q1("SELECT 1 FROM sessions WHERE secret=?", (s["secret"],)):
            await run_io(scan.client_for(s).logout)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


async def me(request: Request):
    c = ctx(request)
    return JSONResponse({"user": {"id": c.owner, "name": c.s["name"], "email": c.s["email"], "admin": c.admin, "kind": c.s["kind"]},
                         "version": VERSION, "immich": store.immich_public_url(), "settings": db.user_settings(c.owner)})


async def settings_save(request: Request):
    c = ctx(request)
    data = await body_json(request)
    res = db.set_user_settings(c.owner, data)
    suggest.touch(c.owner)
    return JSONResponse({"settings": res})


# ---------------------------------------------------------------------------
# Einlesen
# ---------------------------------------------------------------------------
def _status(owner: str) -> dict:
    j = scan.job(owner)
    m = db.meta(owner)
    return {"job": j.public() if j else None, "last_sync": m["last_sync"] if m else None,
            "sync_error": m["sync_error"] if m else None}


async def status(request: Request):
    c = ctx(request)
    return JSONResponse(_status(c.owner))


async def sync_start(request: Request):
    c = ctx(request)
    scan.start(c.owner, c.s)
    return JSONResponse(_status(c.owner))


async def sync_cancel(request: Request):
    c = ctx(request)
    j = scan.job(c.owner)
    if j and j.state == "running":
        j.cancel = True
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------------------
# Vorschläge
# ---------------------------------------------------------------------------
def _page(request: Request, lst: list, mapper=suggest.pub, default=120) -> dict:
    off = intq(request, "offset", 0)
    lim = intq(request, "limit", default, 1, 2000)
    return {"total": len(lst), "offset": off, "items": [mapper(x) for x in lst[off:off + lim]]}


async def overview(request: Request):
    c = ctx(request)
    L = await lib(c)
    data = await run_cpu(L.overview)
    data["status"] = _status(c.owner)
    return JSONResponse(data)


CATEGORIES = {"blurry", "dark", "screenshots", "messenger", "shortvideos", "large", "raworphans", "noalbum"}


async def category(request: Request):
    c = ctx(request)
    name = request.path_params["name"]
    if name not in CATEGORIES:
        return err(404, "Unbekannte Kategorie")
    L = await lib(c)
    lst = await run_cpu(L.category, name)
    out = _page(request, lst)
    out["bytes"] = sum(a.get("size") or 0 for a in lst)
    if name == "messenger":
        out["sources"] = [list(x) for x in _count_sources(lst)]
    return JSONResponse(out)


def _count_sources(lst):
    from collections import Counter
    return Counter(a.src[1] for a in lst).most_common()


def _group_pub(g: dict) -> dict:
    return {"key": g["key"], "keep": g["keep"], "bytes": g["bytes"], "assets": [suggest.pub(a) for a in g["assets"]]}


async def duplicates(request: Request):
    c = ctx(request)
    L = await lib(c)
    lst = await run_cpu(L.duplicates)
    out = _page(request, lst, _group_pub, 30)
    out["bytes"] = sum(g["bytes"] for g in lst)
    return JSONResponse(out)


async def bursts(request: Request):
    c = ctx(request)
    L = await lib(c)
    lst = await run_cpu(L.bursts)
    out = _page(request, lst, _group_pub, 30)
    out["bytes"] = sum(g["bytes"] for g in lst)
    return JSONResponse(out)


async def raw(request: Request):
    c = ctx(request)
    L = await lib(c)
    r = await run_cpu(L.raw_info)
    return JSONResponse({"pairs": len(r["pairs"]), "unstacked": len(r["unstacked"]), "raw_only": r["raw_only"],
                         "raw_bytes": r["raw_bytes"], "orphans": len(r["orphans"]),
                         "orphan_bytes": sum(a.get("size") or 0 for a in r["orphans"]),
                         "examples": [{"raw": suggest.pub(p["raw"]), "jpg": suggest.pub(p["jpg"])} for p in r["unstacked"][:12]]})


def _strip(g: dict) -> dict:
    out = {k: v for k, v in g.items() if k != "ids"}
    if "cities" in g:
        out["cities"] = [_strip(x) for x in g["cities"]]
    return out


async def organize(request: Request):
    c = ctx(request)
    kind = request.path_params["kind"]
    L = await lib(c)
    if kind == "events":
        data = {"items": [_strip(e) for e in await run_cpu(L.events)]}
    elif kind == "sources":
        data = {"items": [_strip(e) for e in await run_cpu(L.sources)]}
    elif kind == "places":
        data = {"items": [_strip(e) for e in await run_cpu(L.places)]}
    elif kind == "folders":
        f = await run_cpu(L.folders)
        data = {"items": [_strip(e) for e in f["folders"]], "random": f["random"], "root": f.get("root")}
    else:
        return err(404, "Unbekannt")
    return JSONResponse(data)


async def group_items(request: Request):
    c = ctx(request)
    kind, key = request.query_params.get("kind", ""), request.query_params.get("key", "")
    L = await lib(c)
    ids = await run_cpu(L.group_ids, kind, key)
    lst = [L.by_id[i] for i in ids if i in L.by_id]
    lst.sort(key=lambda a: a.taken or 0)
    return JSONResponse(_page(request, lst, default=300))


async def months(request: Request):
    c = ctx(request)
    L = await lib(c)
    return JSONResponse({"items": await run_cpu(L.months)})


async def swipe(request: Request):
    c = ctx(request)
    L = await lib(c)
    lst = await run_cpu(L.swipe_queue, request.query_params.get("source", "all"))
    out = _page(request, lst, default=150)
    thumbs.prefetch(c.owner, c.cli, [a["id"] for a in out["items"][:16]])
    out["pending"] = await run_cpu(suggest.pending_summary, c.owner)
    return JSONResponse(out)


# ---------------------------------------------------------------------------
# Entscheiden, löschen, wiederherstellen
# ---------------------------------------------------------------------------
async def marks(request: Request):
    """Markieren ohne sofort zu löschen: trash (vorgemerkt), keep (behalten), fav (Favorit), none (zurücksetzen)."""
    c = ctx(request)
    data = await body_json(request)
    ids = ids_from(data)
    decision = data.get("decision")
    if decision not in ("trash", "keep", "fav", "none"):
        return err(400, "Ungültige Entscheidung")
    L = await lib(c)
    ids = [i for i in ids if i in L.by_id]
    if decision == "fav":
        await c.call(c.cli.set_favorite, ids, True)
    was_fav = [i for i in ids if L.by_id[i].decision == "fav"] if decision == "none" else []
    if was_fav:
        await c.call(c.cli.set_favorite, was_fav, False)
    await run_cpu(_save_marks, c.owner, ids, decision, was_fav)
    return JSONResponse({"ok": True, "pending": await run_cpu(suggest.pending_summary, c.owner)})


def _save_marks(owner: str, ids: list[str], decision: str, was_fav: list[str]) -> None:
    if decision == "fav":
        db.many("UPDATE assets SET fav=1 WHERE owner=? AND id=?", [(owner, i) for i in ids])
        suggest.update(owner, ids, fav=1)
    if was_fav:
        db.many("UPDATE assets SET fav=0 WHERE owner=? AND id=?", [(owner, i) for i in was_fav])
        suggest.update(owner, was_fav, fav=0)
    if decision == "none":
        lib = suggest.library(owner)
        undo = [i for i in ids if i in lib.by_id and not lib.by_id[i].committed]
        db.many("DELETE FROM decisions WHERE owner=? AND id=? AND committed=0", [(owner, i) for i in undo])
        suggest.update(owner, undo, decision=None, committed=None)
    else:
        now = time.time()
        db.many("INSERT OR REPLACE INTO decisions (owner,id,decision,ts,committed) VALUES (?,?,?,?,0)",
                [(owner, i, decision, now) for i in ids])
        suggest.update(owner, ids, decision=decision, committed=0)


async def _trash(c: Ctx, ids: list[str], label: str, raw_follow: bool | None = None) -> dict:
    L = await lib(c)
    ids = [i for i in ids if i in L.by_id and not L.by_id[i]["trashed"] and L.by_id[i]["gone"] is None]
    follow = L.settings["raw_follow"] if raw_follow is None else raw_follow
    extra = L.raw_partners(ids) if follow else []
    all_ids = ids + extra
    if not all_ids:
        return {"count": 0, "bytes": 0, "raw": 0}
    await c.call(c.cli.trash, all_ids)
    nbytes = sum(L.by_id[i].get("size") or 0 for i in all_ids)
    lid = await run_cpu(_save_trash, c.owner, all_ids, label, nbytes)
    return {"count": len(all_ids), "bytes": nbytes, "raw": len(extra), "log": lid}


def _save_trash(owner: str, ids: list[str], label: str, nbytes: int) -> int:
    now = time.time()
    db.many("UPDATE assets SET trashed=1 WHERE owner=? AND id=?", [(owner, i) for i in ids])
    db.many("INSERT OR REPLACE INTO decisions (owner,id,decision,ts,committed) VALUES (?,?,'trash',?,1)", [(owner, i, now) for i in ids])
    suggest.update(owner, ids, trashed=1, decision="trash", committed=1)
    return db.add_log(owner, "trash", label, ids, nbytes)


def _save_keep(owner: str, keep: list[str], clear_dup: bool) -> None:
    if clear_dup:
        db.many("UPDATE assets SET dup=NULL WHERE owner=? AND id=?", [(owner, i) for i in keep])
        suggest.update(owner, keep, dup=None)
    now = time.time()
    db.many("INSERT OR REPLACE INTO decisions (owner,id,decision,ts,committed) VALUES (?,?,'keep',?,1)", [(owner, i, now) for i in keep])
    suggest.update(owner, keep, decision="keep", committed=1)


async def trash(request: Request):
    c = ctx(request)
    data = await body_json(request)
    label = str(data.get("label") or "Aussortiert")[:80]
    rf = data.get("raw_follow")
    return JSONResponse(await _trash(c, ids_from(data), label, None if rf is None else bool(rf)))


async def commit(request: Request):
    c = ctx(request)
    L = await lib(c)
    data = await body_json(request) if (await request.body()) else {}
    ids = [a.id for a in L.pending]
    if "ids" in data:  # nur einen Teil löschen
        want = set(ids_from(data))
        ids = [i for i in ids if i in want]
    return JSONResponse(await _trash(c, ids, str(data.get("label") or "Beim Wischen aussortiert")[:80]))


async def pending(request: Request):
    c = ctx(request)
    L = await lib(c)
    lst = sorted(L.pending, key=lambda a: -(a.get("taken") or 0))
    out = _page(request, lst, default=500)
    out["bytes"] = sum(a.get("size") or 0 for a in lst)
    return JSONResponse(out)


async def resolve(request: Request):
    """Eine Gruppe (Duplikate oder Serie) entscheiden: diese behalten, die anderen in den Papierkorb."""
    c = ctx(request)
    data = await body_json(request)
    keep, drop = ids_from(data, "keep"), ids_from(data, "trash")
    kind = data.get("kind")
    label = "Duplikate aufgeräumt" if kind == "duplicates" else "Serie aufgeräumt" if kind == "bursts" else "Aussortiert"
    res = await _trash(c, [i for i in drop if i not in keep], label) if drop else {"count": 0, "bytes": 0, "raw": 0}
    if kind == "duplicates" and keep:
        await c.call(c.cli.clear_duplicate, keep)
    if keep:
        await run_cpu(_save_keep, c.owner, keep, kind == "duplicates")
    return JSONResponse(res)


async def resolve_all(request: Request):
    """Alle Duplikat-Gruppen oder Serien nach Vorschlag aufräumen."""
    c = ctx(request)
    data = await body_json(request)
    kind = data.get("kind")
    L = await lib(c)
    groups = await run_cpu(L.duplicates) if kind == "duplicates" else await run_cpu(L.bursts) if kind == "bursts" else None
    if groups is None:
        return err(400, "Unbekannt")
    keys = set(data.get("keys") or []) if isinstance(data.get("keys"), list) else None
    keep, drop = [], []
    for g in groups:
        if keys is not None and g["key"] not in keys:
            continue
        keep.extend(g["keep"])
        drop.extend(a["id"] for a in g["assets"] if a["id"] not in g["keep"])
    res = await _trash(c, drop, "Alle Duplikate aufgeräumt" if kind == "duplicates" else "Alle Serien aufgeräumt")
    if kind == "duplicates" and keep:
        await c.call(c.cli.clear_duplicate, keep)
    if keep:
        await run_cpu(_save_keep, c.owner, keep, kind == "duplicates")
    return JSONResponse(res)


async def stack(request: Request):
    """RAW+JPG-Paare in Immich stapeln (JPG oben)."""
    c = ctx(request)
    L = await lib(c)
    r = await run_cpu(L.raw_info)
    pairs = list(r["unstacked"])
    done, failed = 0, 0
    for p in pairs:
        try:
            st = await c.call(c.cli.create_stack, [p["jpg"]["id"], p["raw"]["id"]])
            sid = (st or {}).get("id")
            db.run("UPDATE assets SET stack=?, stack_primary=1 WHERE owner=? AND id=?", (sid, c.owner, p["jpg"].id))
            db.run("UPDATE assets SET stack=?, stack_primary=0 WHERE owner=? AND id=?", (sid, c.owner, p["raw"].id))
            suggest.update(c.owner, [p["jpg"].id], stack=sid, stack_primary=1)
            suggest.update(c.owner, [p["raw"].id], stack=sid, stack_primary=0)
            done += 1
        except ApiError as e:
            if e.status == 401:
                raise
            failed += 1
    if done:
        db.add_log(c.owner, "stack", f"{done} RAW+JPG-Paare gestapelt", [p["raw"].id for p in pairs[:done]])
    return JSONResponse({"done": done, "failed": failed})


async def history(request: Request):
    c = ctx(request)
    rows = db.q("SELECT lid, ts, kind, label, count, bytes, restored, ids FROM log WHERE owner=? ORDER BY ts DESC LIMIT 200", (c.owner,))
    out = []
    for r in rows:
        ids = json.loads(r["ids"] or "[]")
        out.append({"id": r["lid"], "ts": r["ts"], "kind": r["kind"], "label": r["label"], "count": r["count"], "bytes": r["bytes"],
                    "restored": r["restored"], "covers": ids[:6]})
    freed = db.q1("SELECT IFNULL(SUM(bytes),0) b, IFNULL(SUM(count),0) n FROM log WHERE owner=? AND kind='trash' AND restored IS NULL", (c.owner,))
    return JSONResponse({"items": out, "freed": freed["b"], "freed_count": freed["n"]})


async def restore(request: Request):
    c = ctx(request)
    lid = int(request.path_params["lid"])
    r = db.q1("SELECT * FROM log WHERE owner=? AND lid=?", (c.owner, lid))
    if not r or r["kind"] != "trash":
        return err(404, "Nicht gefunden")
    if r["restored"]:
        return err(409, "Schon wiederhergestellt.")
    ids = json.loads(r["ids"] or "[]")
    try:
        await c.call(c.cli.restore, ids)
    except ApiError as e:
        if e.status in (400, 404):
            return err(409, "Nicht mehr im Immich-Papierkorb – vermutlich schon endgültig gelöscht.")
        raise
    db.many("UPDATE assets SET trashed=0, gone=NULL WHERE owner=? AND id=?", [(c.owner, i) for i in ids])
    db.many("DELETE FROM decisions WHERE owner=? AND id=?", [(c.owner, i) for i in ids])
    db.run("UPDATE log SET restored=? WHERE lid=?", (time.time(), lid))
    suggest.update(c.owner, ids, trashed=0, gone=None, decision=None, committed=None)
    return JSONResponse({"ok": True, "count": len(ids)})


async def empty_trash(request: Request):
    c = ctx(request)
    n = await c.call(c.cli.empty_trash)
    db.run("UPDATE log SET restored=-1 WHERE owner=? AND kind='trash' AND restored IS NULL", (c.owner,))
    return JSONResponse({"ok": True, "count": n})


# ---------------------------------------------------------------------------
# Alben
# ---------------------------------------------------------------------------
async def albums(request: Request):
    c = ctx(request)
    lst = await c.call(c.cli.albums)
    out = [{"id": a["id"], "name": a.get("albumName"), "count": a.get("assetCount"), "cover": a.get("albumThumbnailAssetId"),
            "shared": bool(a.get("shared"))} for a in lst or []]
    out.sort(key=lambda a: (a["name"] or "").lower())
    return JSONResponse({"items": out})


async def album_save(request: Request):
    c = ctx(request)
    data = await body_json(request)
    L = await lib(c)
    if data.get("kind"):
        ids = await run_cpu(L.group_ids, str(data["kind"]), str(data.get("key", "")))
        if "exclude" in data:
            ex = set(ids_from(data, "exclude"))
            ids = [i for i in ids if i not in ex]
    else:
        ids = ids_from(data)
    ids = [i for i in ids if i in L.by_id and not L.by_id[i]["trashed"] and L.by_id[i].get("decision") != "trash"]
    if not ids:
        return err(400, "Keine Fotos ausgewählt.")
    album_id = data.get("album_id")
    if album_id:
        if not is_uuid(album_id):
            return err(400, "Ungültiges Album")
        added = await c.call(c.cli.add_to_album, album_id, ids)
        name = str(data.get("name") or "Album")[:120]
        res = {"album_id": album_id, "added": added}
    else:
        name = str(data.get("name") or "").strip()[:120]
        if not name:
            return err(400, "Bitte einen Namen für das Album eingeben.")
        album = await c.call(c.cli.create_album, name, ids)
        res = {"album_id": album.get("id"), "added": len(ids)}
    db.many("UPDATE assets SET in_album=1 WHERE owner=? AND id=?", [(c.owner, i) for i in ids])
    suggest.update(c.owner, ids, in_album=1)
    db.add_log(c.owner, "album", f"Album „{name}“: {len(ids)} hinzugefügt", ids[:200])
    res["url"] = f"{store.immich_public_url()}/albums/{res['album_id']}" if res.get("album_id") else None
    return JSONResponse(res)


# ---------------------------------------------------------------------------
# Bilder und Videos aus Immich durchreichen
# ---------------------------------------------------------------------------
async def thumb(request: Request):
    c = ctx(request)
    aid = request.path_params["id"]
    if not is_uuid(aid):
        return err(400, "Ungültige ID")
    size = "preview" if request.query_params.get("size") == "preview" else "thumbnail"
    t0 = time.perf_counter()
    data, ctype, src = await c.call(thumbs.get, c.owner, c.cli, aid, size)
    ms = (time.perf_counter() - t0) * 1000
    return Response(data, media_type=ctype, headers={"Cache-Control": "private, max-age=604800, immutable",
                                                     "Server-Timing": f"{src};dur={ms:.1f}"})


async def _stream(c: Ctx, request: Request, path: str, extra_headers: dict | None = None):
    rng = request.headers.get("range")
    resp = await c.call(c.cli.open, "GET", path, headers={"Range": rng} if rng else None, timeout=60)
    headers = {k: resp.headers[k] for k in ("Content-Range", "Content-Length", "Accept-Ranges", "Content-Type", "Content-Disposition")
               if resp.headers.get(k)}
    headers["Cache-Control"] = "private, max-age=3600"
    headers.update(extra_headers or {})

    def it():
        try:
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            resp.close()
    return StreamingResponse(it(), status_code=resp.status, headers=headers)


async def video(request: Request):
    c = ctx(request)
    aid = request.path_params["id"]
    if not is_uuid(aid):
        return err(400, "Ungültige ID")
    return await _stream(c, request, f"/assets/{aid}/video/playback")


async def original(request: Request):
    c = ctx(request)
    aid = request.path_params["id"]
    if not is_uuid(aid):
        return err(400, "Ungültige ID")
    return await _stream(c, request, f"/assets/{aid}/original")


# ---------------------------------------------------------------------------
# System (Admins)
# ---------------------------------------------------------------------------
def _vkey(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.-]", v or "0"))


async def system(request: Request):
    c = ctx(request)
    info = {"version": VERSION, "admin": c.admin, "immich_url": store.immich_url(),
            "immich_public_url": store.settings().get("immich_public_url") or ""}
    info["immich_version"] = await run_io(c.cli.server_version)
    if c.admin:
        st = await run_io(updatewatch.check, request.query_params.get("check") == "1")
        info["latest"] = st.get("latest_version")
        info["installed"] = st.get("installed")
        info["changes"] = st.get("changes", [])[:20]
        info["more"] = bool(st.get("more"))
        info["check_error"] = st.get("error")
        sec, _ = updatewatch.describe(st.get("changes", []))
        info["security"] = sec
        info["update"] = bool(st.get("behind")) if st.get("installed") else bool(info["latest"] and _vkey(info["latest"]) > _vkey(VERSION))
        info["repo"] = REPO
        n = updatewatch.ntfy_settings()
        info["ntfy"] = {"url": n["url"], "topic": n["topic"], "notify": n["notify"], "has_token": bool(n["token"]), "click": n["click"]}
        info["users"] = [{"name": r["name"], "last_sync": r["last_sync"]} for r in db.q("SELECT name, last_sync FROM user_meta ORDER BY name")]
    return JSONResponse(info)


async def notify_settings(request: Request):
    need_admin(request)
    data = await body_json(request)
    cur = dict(store.settings().get("ntfy") or {})
    topic = str(data.get("topic", cur.get("topic", ""))).strip()
    if topic and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic):
        return err(400, "Das Thema darf nur Buchstaben, Zahlen, - und _ enthalten (max. 64 Zeichen).")
    url = str(data.get("url", cur.get("url", "")) or "").strip().rstrip("/")
    if url and not re.fullmatch(r"https?://[^\s/]+(/[^\s]*)?", url):
        return err(400, "Ungültige ntfy-Adresse.")
    click = str(data.get("click", cur.get("click", "")) or "").strip()
    if click and not re.fullmatch(r"https?://\S+", click):
        return err(400, "Ungültige Adresse von ImmichHelper.")
    cur.update(topic=topic, url=url, notify=bool(data.get("notify", True)), click=click)
    if "token" in data:
        tok = str(data.get("token") or "").strip()
        if tok == "-":
            cur["token"] = ""
        elif tok:
            cur["token"] = tok
    store.set_setting("ntfy", cur)
    return JSONResponse({"ok": True})


async def notify_test(request: Request):
    need_admin(request)
    try:
        await run_io(updatewatch.push, "ImmichHelper: Test", "Push-Nachrichten kommen an. Du wirst bei neuen Versionen benachrichtigt.", 3, ("white_check_mark",))
    except Exception as e:  # noqa: BLE001
        return err(400, f"Senden fehlgeschlagen: {e}")
    return JSONResponse({"ok": True})


async def system_update(request: Request):
    need_admin(request)
    script = BASE / "install.sh"
    if not script.exists():
        return err(500, "install.sh nicht gefunden.")
    try:
        subprocess.Popen(["systemd-run", "--unit", f"immichhelper-update-{int(time.time())}", "--collect",
                          "/usr/bin/env", "bash", str(script), "--update"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        return err(500, "systemd-run fehlt – bitte im Container „immichhelper update“ ausführen.")
    return JSONResponse({"ok": True})


def _rss_mb() -> int | None:
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


async def diag(request: Request):
    """Selbsttest: Wie schnell antwortet Immich, kommen Bilder an, wie viel Speicher wird gebraucht?"""
    c = ctx(request)
    out: dict = {"version": VERSION, "ram_mb": _rss_mb(), "cache": thumbs.stats(), "checks": []}

    def check(label, fn):
        t0 = time.perf_counter()
        try:
            detail = fn()
            out["checks"].append({"label": label, "ok": True, "ms": round((time.perf_counter() - t0) * 1000), "detail": detail})
        except ImmichError as e:
            out["checks"].append({"label": label, "ok": False, "ms": round((time.perf_counter() - t0) * 1000), "detail": e.message})
        except Exception as e:  # noqa: BLE001
            out["checks"].append({"label": label, "ok": False, "ms": round((time.perf_counter() - t0) * 1000), "detail": str(e)})

    def run_checks():
        check("Immich erreichbar", lambda: "ja" if c.cli.ping() else "keine Antwort")
        row = db.q1("SELECT id FROM assets WHERE owner=? AND type='IMAGE' AND trashed=0 AND gone IS NULL ORDER BY RANDOM() LIMIT 1", (c.owner,))
        if row:
            for size, label in (("thumbnail", "Kleines Vorschaubild"), ("preview", "Große Vorschau")):
                check(label, lambda size=size: (lambda d: f"{len(d[0]) // 1024} KB, {d[1]}")(thumbs.fetch(c.cli, row["id"], size)))
        t0 = time.perf_counter()
        suggest.library(c.owner)
        out["library_ms"] = round((time.perf_counter() - t0) * 1000)
        out["assets"] = len(suggest.library(c.owner).all)
    await run_io(run_checks)
    out["ram_mb_after"] = _rss_mb()
    return JSONResponse(out)


async def health(request: Request):
    return JSONResponse({"ok": True, "version": VERSION})


# ---------------------------------------------------------------------------
# Oberfläche
# ---------------------------------------------------------------------------
_html_cache: dict[str, str] = {}


async def index(request: Request):
    if "index" not in _html_cache or VERSION == "dev":
        _html_cache["index"] = (FRONTEND / "index.html").read_text().replace("{{VERSION}}", VERSION)
    return Response(_html_cache["index"], media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})


CSP = ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; object-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")


class Guard:
    """Sicherheits-Header und CSRF-Schutz: Änderungen nur mit eigenem Header (den fremde Seiten nicht setzen können)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["method"] not in ("GET", "HEAD", "OPTIONS") and scope["path"].startswith("/api/"):
            if dict(scope["headers"]).get(b"x-immichhelper") != b"1":
                return await err(403, "Anfrage abgelehnt (CSRF-Schutz).")(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                names = {k.lower() for k, _ in headers}
                extra = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"same-origin"),
                         (b"x-frame-options", b"SAMEORIGIN"), (b"content-security-policy", CSP.encode())]
                headers.extend(e for e in extra if e[0] not in names)
            await send(message)
        await self.app(scope, receive, send_wrapper)


async def api_error(request: Request, exc: ApiError):
    return err(exc.status, exc.message)


@asynccontextmanager
async def lifespan(app):
    store.load()
    db.conn()
    if not store.immich_url():
        print("ImmichHelper: Noch keine Immich-Adresse eingestellt – bitte im Browser öffnen.", flush=True)
    if os.environ.get("IH_BACKGROUND", "1") == "1":
        scan.start_background()
        updatewatch.start_background()
    yield


routes = [
    Route("/api/health", health),
    Route("/api/setup", setup_info),
    Route("/api/setup", setup_save, methods=["POST"]),
    Route("/api/login", login, methods=["POST"]),
    Route("/api/logout", logout, methods=["POST"]),
    Route("/api/me", me),
    Route("/api/settings", settings_save, methods=["PUT"]),
    Route("/api/status", status),
    Route("/api/sync", sync_start, methods=["POST"]),
    Route("/api/sync/cancel", sync_cancel, methods=["POST"]),
    Route("/api/overview", overview),
    Route("/api/cat/{name}", category),
    Route("/api/duplicates", duplicates),
    Route("/api/bursts", bursts),
    Route("/api/raw", raw),
    Route("/api/organize/{kind}", organize),
    Route("/api/group", group_items),
    Route("/api/months", months),
    Route("/api/swipe", swipe),
    Route("/api/marks", marks, methods=["POST"]),
    Route("/api/marks/pending", pending),
    Route("/api/marks/commit", commit, methods=["POST"]),
    Route("/api/trash", trash, methods=["POST"]),
    Route("/api/trash/empty", empty_trash, methods=["POST"]),
    Route("/api/resolve", resolve, methods=["POST"]),
    Route("/api/resolve/all", resolve_all, methods=["POST"]),
    Route("/api/stack", stack, methods=["POST"]),
    Route("/api/history", history),
    Route("/api/history/{lid:int}/restore", restore, methods=["POST"]),
    Route("/api/albums", albums),
    Route("/api/albums", album_save, methods=["POST"]),
    Route("/api/thumb/{id}", thumb),
    Route("/api/video/{id}", video),
    Route("/api/original/{id}", original),
    Route("/api/system", system),
    Route("/api/system/diag", diag),
    Route("/api/system/immich", setup_save, methods=["PUT"]),
    Route("/api/system/update", system_update, methods=["POST"]),
    Route("/api/system/notify", notify_settings, methods=["PUT"]),
    Route("/api/system/notify/test", notify_test, methods=["POST"]),
    Route("/", index),
    Mount("/static", StaticFiles(directory=FRONTEND), name="static"),
]

app = Starlette(routes=routes, lifespan=lifespan, exception_handlers={ApiError: api_error}, middleware=[Middleware(Guard)])
