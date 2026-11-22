"""Vorschaubilder schnell ausliefern.

Vorher wurde jedes Bild einzeln bei Immich geholt – mit neuer Verbindung, ohne Zwischenspeicher und in
Konkurrenz zur Bildprüfung im Hintergrund. Das führte zu schwarzen/leeren Vorschauen beim Wischen.

Jetzt:
- Zwischenspeicher auf der Festplatte des Containers (überlebt Neustarts, IH_THUMB_DISK_MB, Standard 1500) und für
  die kleinen Rasterbilder zusätzlich im Arbeitsspeicher (IH_THUMB_MEM_MB, Standard 48). Große Vorschauen liegen nur
  auf der Platte – das Betriebssystem hält oft genutzte Dateien ohnehin im Speicher, ohne dass das Programm wächst.
- Begrenzte Zahl gleichzeitiger Anfragen an Immich; was du gerade ansiehst, hat Vorrang vor Vorladen und Bildprüfung.
- Dauerhafte Verbindungen zu Immich (Keep-Alive) statt für jedes Bild eine neue.
- Gleichzeitige Anfragen für dasselbe Bild holen es nur einmal.
- Beim Wischen werden die nächsten Bilder schon vorab geladen.
- Die Bildprüfung im Hintergrund pausiert kurz, solange du Bilder ansiehst.
"""
from __future__ import annotations

import concurrent.futures as cf
import contextlib
import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import urllib3

from . import db
from .immich import Immich, ImmichError, _message

log = logging.getLogger("immichhelper.thumbs")
MEM_CAP = int(os.environ.get("IH_THUMB_MEM_MB", "48")) * 1024 * 1024
DISK_CAP = int(os.environ.get("IH_THUMB_DISK_MB", "1500")) * 1024 * 1024
SIZES = ("thumbnail", "preview")

_pool = urllib3.PoolManager(
    num_pools=4, maxsize=24, block=False, retries=False,
    timeout=urllib3.Timeout(connect=4.0, read=20.0),
    cert_reqs="CERT_NONE" if os.environ.get("IH_IMMICH_INSECURE", "0") == "1" else "CERT_REQUIRED",
)
if os.environ.get("IH_IMMICH_INSECURE", "0") == "1":
    urllib3.disable_warnings()

# Wie viele Bilder gleichzeitig bei Immich angefragt werden: was du gerade ansiehst, hat eigene Plätze;
# Vorladen und Bildprüfung teilen sich wenige – so wird Immich nie überrannt und dein Bild nie hintangestellt.
_front = threading.BoundedSemaphore(int(os.environ.get("IH_IMMICH_PARALLEL", "8")))
_back = threading.BoundedSemaphore(3)
_none = contextlib.nullcontext()
_last_view = 0.0  # wann zuletzt jemand Bilder angesehen hat (für die Bildprüfung im Hintergrund)


# ---------------------------------------------------------------------------
# Arbeitsspeicher
# ---------------------------------------------------------------------------
class _Mem:
    def __init__(self, cap: int):
        self.cap = cap
        self.size = 0
        self.d: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
        self.lock = threading.Lock()

    def get(self, k: str):
        with self.lock:
            v = self.d.get(k)
            if v is not None:
                self.d.move_to_end(k)
            return v

    def put(self, k: str, v: tuple[bytes, str]) -> None:
        if len(v[0]) > self.cap // 8:
            return
        with self.lock:
            old = self.d.pop(k, None)
            if old:
                self.size -= len(old[0])
            self.d[k] = v
            self.size += len(v[0])
            while self.size > self.cap and self.d:
                _, (b, _) = self.d.popitem(last=False)
                self.size -= len(b)


_mem = _Mem(MEM_CAP)


# ---------------------------------------------------------------------------
# Festplatte
# ---------------------------------------------------------------------------
class _Disk:
    def __init__(self):
        self.lock = threading.Lock()
        self.size: int | None = None  # wird beim ersten Gebrauch ermittelt

    @property
    def root(self) -> Path:
        return db.STATE_DIR / "thumbs"

    def path(self, k: str) -> Path:
        return self.root / k[:2] / k

    def _measure(self) -> int:
        total = 0
        if self.root.exists():
            for p in self.root.rglob("*"):
                if p.is_file():
                    try:
                        total += p.stat().st_size
                    except OSError:
                        pass
        return total

    def get(self, k: str):
        p = self.path(k)
        try:
            data = p.read_bytes()
        except OSError:
            return None
        try:
            now = time.time()
            if now - p.stat().st_mtime > 3600:  # „zuletzt benutzt“ für das Aufräumen
                os.utime(p, (now, now))
        except OSError:
            pass
        ctype = "image/webp" if data[:4] == b"RIFF" else "image/jpeg"
        return data, ctype

    def put(self, k: str, data: bytes, evict: bool = True) -> None:
        if DISK_CAP <= 0:
            return
        with self.lock:
            if self.size is None:
                self.size = self._measure()
            if self.size + len(data) > DISK_CAP:
                if not evict:
                    return
                self._evict(int(DISK_CAP * 0.85))
            p = self.path(k)
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_suffix(".tmp")
                tmp.write_bytes(data)
                os.replace(tmp, p)
                self.size += len(data)
            except OSError as e:
                log.warning("Vorschau nicht gespeichert: %s", e)

    def _evict(self, target: int) -> None:
        files = []
        for p in self.root.rglob("*"):
            if p.is_file():
                try:
                    st = p.stat()
                    files.append((st.st_mtime, st.st_size, p))
                except OSError:
                    pass
        files.sort()
        total = sum(f[1] for f in files)
        for _, sz, p in files:
            if total <= target:
                break
            try:
                p.unlink()
                total -= sz
            except OSError:
                pass
        self.size = total


_disk = _Disk()


# ---------------------------------------------------------------------------
def key(aid: str, size: str, checksum: str | None) -> str:
    """Bearbeitet jemand ein Foto in Immich, ändert sich die Prüfsumme – und damit der Schlüssel."""
    tag = hashlib.sha1((checksum or "").encode()).hexdigest()[:10]
    return f"{aid}.{size[0]}.{tag}"


def fetch(cli: Immich, aid: str, size: str, *, background: bool = False, analysis: bool = False) -> tuple[bytes, str]:
    """Direkt bei Immich holen – über eine dauerhafte Verbindung. Weiterleitungen (z. B. durch einen Proxy) werden befolgt."""
    if not cli.base:
        raise ImmichError(503, "Die Adresse von Immich ist noch nicht eingestellt.")
    url = cli.url(f"/assets/{aid}/thumbnail", {"size": size})
    sem = _none if analysis else _back if background else _front  # Bildprüfung begrenzt sich über ihre Arbeiter selbst
    with sem:
        for _ in range(4):
            try:
                r = _pool.request("GET", url, headers=cli._headers(), preload_content=True, redirect=False)
            except urllib3.exceptions.TimeoutError:
                raise ImmichError(504, "Immich antwortet nicht rechtzeitig.") from None
            except urllib3.exceptions.HTTPError as e:
                raise ImmichError(502, f"Immich ist nicht erreichbar ({e}).") from None
            if r.status in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                nxt = urljoin(url, r.headers["Location"])
                if urlsplit(nxt).hostname != urlsplit(url).hostname:
                    raise ImmichError(502, "Immich leitet auf eine andere Adresse um – bitte in den Einstellungen die direkte Adresse im Heimnetz eintragen.")
                url = nxt
                continue
            break
    if r.status >= 400:
        raise ImmichError(r.status, _message(r.status, r.data))
    ctype = r.headers.get("Content-Type") or ""
    if not ctype.startswith("image/") or len(r.data) < 16:
        raise ImmichError(502, f"Immich hat kein Bild geliefert ({ctype or 'unbekannt'}, Status {r.status}).")
    return r.data, ctype


_inflight: dict[str, threading.Event] = {}
_inflight_lock = threading.Lock()


def get(owner: str, cli: Immich, aid: str, size: str, *, interactive: bool = True) -> tuple[bytes, str, str]:
    """(Daten, Typ, Quelle) – Quelle ist „mem“, „disk“ oder „immich“."""
    global _last_view
    if interactive:
        _last_view = time.monotonic()
    row = db.q1("SELECT checksum FROM assets WHERE owner=? AND id=?", (owner, aid))
    if row is None:
        # Unbekanntes Foto (noch nicht eingelesen): nicht zwischenspeichern, Immich prüft die Berechtigung
        data, ctype = fetch(cli, aid, size)
        return data, ctype, "immich"
    k = key(aid, size, row["checksum"])
    hit = _mem.get(k)
    if hit:
        return hit[0], hit[1], "mem"
    hit = _disk.get(k)
    if hit:
        if size == "thumbnail":
            _mem.put(k, hit)
        return hit[0], hit[1], "disk"

    # Nur einmal holen, auch wenn mehrere gleichzeitig fragen (Vorladen + Anzeigen)
    with _inflight_lock:
        ev = _inflight.get(k)
        leader = ev is None
        if leader:
            ev = _inflight[k] = threading.Event()
    if not leader:
        ev.wait(50)
        hit = _mem.get(k) or _disk.get(k)
        if hit:
            return hit[0], hit[1], "mem"
        # Vorgänger ist gescheitert → selbst versuchen
        data, ctype = fetch(cli, aid, size)
        return data, ctype, "immich"
    try:
        data, ctype = fetch(cli, aid, size, background=not interactive)
        if size == "thumbnail" or DISK_CAP <= 0:
            _mem.put(k, (data, ctype))
        _disk.put(k, data)
        return data, ctype, "immich"
    finally:
        with _inflight_lock:
            _inflight.pop(k, None)
        ev.set()


def remember(aid: str, size: str, checksum: str | None, data: bytes, ctype: str = "image/jpeg") -> None:
    """Von der Bildprüfung ohnehin geladene Vorschau aufheben – nur solange Platz ist, nichts verdrängen."""
    _disk.put(key(aid, size, checksum), data, evict=False)


# ---------------------------------------------------------------------------
# Vorladen
# ---------------------------------------------------------------------------
_pre = cf.ThreadPoolExecutor(max_workers=3, thread_name_prefix="prefetch")
_queued: set[str] = set()
_queued_lock = threading.Lock()


def prefetch(owner: str, cli: Immich, ids: list[str], sizes=SIZES) -> None:
    rows = {}
    if ids:
        marks = ",".join("?" * len(ids))
        rows = {r["id"]: r["checksum"] for r in db.q(f"SELECT id, checksum FROM assets WHERE owner=? AND id IN ({marks})", (owner, *ids))}
    # Erst alle kleinen Bilder (schnell, sofort etwas zu sehen), dann die großen
    for size in sizes:
        for aid in ids:
            if aid not in rows:
                continue
            k = key(aid, size, rows[aid])
            if _mem.get(k) or _disk.path(k).exists():
                continue
            with _queued_lock:
                if k in _queued:
                    continue
                _queued.add(k)

            def job(aid=aid, size=size, k=k):
                try:
                    get(owner, cli, aid, size, interactive=False)
                except ImmichError:
                    pass
                except Exception as e:  # noqa: BLE001
                    log.debug("Vorladen fehlgeschlagen: %s", e)
                finally:
                    with _queued_lock:
                        _queued.discard(k)
            _pre.submit(job)


def wait_for_quiet(max_wait: float = 5.0) -> None:
    """Bildprüfung im Hintergrund: kurz warten, solange jemand gerade Bilder ansieht."""
    t0 = time.monotonic()
    while time.monotonic() - _last_view < 1.5 and time.monotonic() - t0 < max_wait:
        time.sleep(0.25)


def stats() -> dict:
    if _disk.size is None:
        with _disk.lock:
            if _disk.size is None:
                _disk.size = _disk._measure()
    return {"mem_mb": round(_mem.size / 1048576, 1), "mem_items": len(_mem.d), "mem_cap_mb": MEM_CAP // 1048576,
            "disk_mb": round((_disk.size or 0) / 1048576, 1), "disk_cap_mb": DISK_CAP // 1048576}
