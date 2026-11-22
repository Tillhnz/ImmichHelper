"""Vorschläge zum Aussortieren und zum Ordnen – berechnet aus der lokalen Kopie der Metadaten.

Aussortieren: unscharf, Fehlaufnahmen (schwarz/einfarbig), Screenshots, Messenger-Bilder, sehr kurze Videos,
große Dateien, Duplikate (von Immich), Serien (schnell hintereinander, sehr ähnlich), RAW-Dateien ohne JPG.
Ordnen: Ereignisse (Ausflüge/Reisen, besondere Tage), Quellen (Kamera, WhatsApp …), Orte, Ordner.

Nie vorgeschlagen wird, was du behalten hast. Favoriten nur, wenn das in den Einstellungen so gewünscht ist.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from collections import Counter, defaultdict
from datetime import date, datetime

from . import db
from .analyze import hamming

RAW_EXT = {"raf", "cr2", "cr3", "nef", "nrw", "arw", "srf", "sr2", "dng", "orf", "rw2", "pef", "srw", "raw", "rwl", "3fr", "iiq", "x3f"}
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS_SHORT = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli", "Aug.", "Sep.", "Okt.", "Nov.", "Dez."]

SCREENSHOT = re.compile(r"^(screenshot|screen[ _-]?shot|bildschirmfoto|scrnli|screencapture|capture d|schermafbeelding)", re.I)
SCREENREC = re.compile(r"^(screen[ _-]?record|bildschirmaufnahme|screenrecord|rpreplay|screen_recording)", re.I)
MESSENGER = [
    ("whatsapp", "WhatsApp", re.compile(r"^((IMG|VID|AUD|PTT|STK|DOC)-\d{8}-WA\d+|WhatsApp (Image|Video|Bild))", re.I)),
    ("telegram", "Telegram", re.compile(r"^(photo|video|file)_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}", re.I)),
    ("signal", "Signal", re.compile(r"^signal-\d{4}-\d{2}-\d{2}", re.I)),
    ("threema", "Threema", re.compile(r"^threema-", re.I)),
    ("facebook", "Facebook/Messenger", re.compile(r"^(received_\d+|FB_IMG_\d+)", re.I)),
    ("snapchat", "Snapchat", re.compile(r"^snapchat-\d+", re.I)),
]
MESSENGER_PATH = [("whatsapp", "WhatsApp", re.compile(r"/whatsapp", re.I)), ("telegram", "Telegram", re.compile(r"/telegram", re.I)),
                  ("signal", "Signal", re.compile(r"/signal/", re.I))]

_cache_lock = threading.Lock()


def ext(name: str | None) -> str:
    if not name or "." not in name:
        return ""
    return name.rsplit(".", 1)[1].lower()


def stem(name: str | None) -> str:
    if not name:
        return ""
    return name.rsplit(".", 1)[0].lower() if "." in name else name.lower()


def is_raw(a: dict) -> bool:
    return ext(a["name"]) in RAW_EXT


def day_of(a: dict) -> str:
    loc = a.get("local") or ""
    if len(loc) >= 10:
        return loc[:10]
    if a.get("taken"):
        return datetime.fromtimestamp(a["taken"]).strftime("%Y-%m-%d")
    return "0000-00-00"


def nice_make(make: str | None, model: str | None) -> str | None:
    if not make and not model:
        return None
    make = (make or "").strip()
    model = (model or "").strip()
    mk = {"FUJIFILM": "Fujifilm", "NIKON CORPORATION": "Nikon", "NIKON": "Nikon", "CANON": "Canon", "SONY": "Sony",
          "OLYMPUS CORPORATION": "Olympus", "OLYMPUS IMAGING CORP.": "Olympus", "OM DIGITAL SOLUTIONS": "OM System",
          "PANASONIC": "Panasonic", "SAMSUNG": "Samsung", "XIAOMI": "Xiaomi", "HUAWEI": "Huawei", "GOOGLE": "Google",
          "APPLE": "Apple", "ONEPLUS": "OnePlus", "LEICA CAMERA AG": "Leica", "RICOH IMAGING COMPANY, LTD.": "Ricoh",
          "GOPRO": "GoPro", "DJI": "DJI"}.get(make.upper(), make.title() if make.isupper() and len(make) > 3 else make)
    if model.lower().startswith(mk.lower()):
        return model if not model.isupper() or len(model) < 6 else mk + model[len(mk):]
    return f"{mk} {model}".strip()


def source_of(a: dict) -> tuple[str, str, str]:
    """(Schlüssel, Bezeichnung, Art) – woher stammt das Bild?"""
    name = a.get("name") or ""
    path = a.get("path") or ""
    for key, label, rx in MESSENGER:
        if rx.search(name):
            return f"msg:{key}", label, "messenger"
    for key, label, rx in MESSENGER_PATH:
        if rx.search(path):
            return f"msg:{key}", label, "messenger"
    if SCREENREC.search(name):
        return "screen:rec", "Bildschirmaufnahmen", "screen"
    if SCREENSHOT.search(name) or "/screenshots/" in path.lower() or (ext(name) == "png" and not a.get("make") and a["type"] == "IMAGE"):
        return "screen:shot", "Screenshots", "screen"
    cam = nice_make(a.get("make"), a.get("model"))
    if cam:
        return f"cam:{cam.lower()}", cam, "camera"
    return "none", "Ohne Kamera-Angabe", "none"


def pub(a: dict) -> dict:
    """Kurzform für die Oberfläche."""
    return {"id": a["id"], "type": "V" if a["type"] == "VIDEO" else "I", "name": a["name"], "local": a.get("local"),
            "taken": a.get("taken"), "size": a.get("size"), "w": a.get("w"), "h": a.get("h"), "fav": bool(a.get("fav")),
            "dur": a.get("dur"), "sharp": a.get("sharp"), "bright": a.get("bright"), "archived": bool(a.get("archived")),
            "place": ", ".join(x for x in (a.get("city"), a.get("country")) if x) or None,
            "cam": nice_make(a.get("make"), a.get("model")), "raw": is_raw(a),
            "mark": "trash" if a.get("decision") == "trash" and not a.get("committed") else None}


def fmt_range(d1: str, d2: str) -> str:
    a, b = date.fromisoformat(d1), date.fromisoformat(d2)
    if a == b:
        return f"{a.day}. {MONTHS[a.month - 1]} {a.year}"
    if a.year == b.year and a.month == b.month:
        return f"{a.day}.–{b.day}. {MONTHS[a.month - 1]} {a.year}"
    if a.year == b.year:
        return f"{a.day}. {MONTHS_SHORT[a.month - 1]} – {b.day}. {MONTHS_SHORT[b.month - 1]} {a.year}"
    return f"{a.day}. {MONTHS_SHORT[a.month - 1]} {a.year} – {b.day}. {MONTHS_SHORT[b.month - 1]} {b.year}"


def month_label(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{MONTHS[x.month - 1]} {x.year}"


# ---------------------------------------------------------------------------
# Kompakter Speicher für Fotos: ein schlankes Objekt je Foto statt eines Wörterbuchs
# (bei 40.000 Fotos ca. 25 MB statt über 200 MB) – und es wird nicht bei jedem Wisch neu aufgebaut,
# sondern direkt geändert.
# ---------------------------------------------------------------------------
_FIELDS = ("id", "type", "name", "path", "taken", "local", "size", "w", "h", "make", "model", "city", "state", "country",
           "dur", "fav", "archived", "dup", "stack", "stack_primary", "in_album", "trashed", "gone",
           "sharp", "bright", "contrast", "hi", "dhash", "decision", "committed")
_SLOTS = _FIELDS + ("src", "raw", "stem")  # einmal berechnet: Herkunft, RAW-Datei?, Dateiname ohne Endung
_INTERN = {"type", "make", "model", "city", "state", "country", "decision"}


class Asset:
    __slots__ = _SLOTS

    def __getitem__(self, k):
        return getattr(self, k)

    def get(self, k, default=None):
        v = getattr(self, k, default)
        return default if v is None else v


def _asset(row) -> Asset:
    a = Asset()
    for f in _FIELDS:
        v = row[f]
        if f in _INTERN and v is not None:
            v = sys.intern(v)
        elif f in ("sharp", "bright", "contrast", "hi") and v is not None:
            v = round(v, 1)
        elif f == "gone":
            v = None if v is None else 1
        setattr(a, f, v)
    a.src = source_of(a)
    a.raw = is_raw(a)
    a.stem = sys.intern(stem(a.name))
    return a


class Library:
    """Alle Fotos und Videos eines Benutzers im Speicher.

    Die Fotos werden nur nach dem Einlesen neu geladen. Entscheidungen, Löschen, Prüfergebnisse usw. ändern die
    Objekte direkt (siehe update()) – danach werden nur die abgeleiteten Listen und Vorschläge neu berechnet,
    und zwar erst, wenn sie gebraucht werden.
    """

    def __init__(self, owner: str):
        self.owner = owner
        self.gen = db.version(owner)
        rows = db.q("""SELECT a.id, a.type, a.name, a.path, a.taken, a.local, a.size, a.w, a.h, a.make, a.model, a.city, a.state,
                              a.country, a.dur, a.fav, a.archived, a.dup, a.stack, a.stack_primary, a.in_album, a.trashed, a.gone,
                              n.sharp, n.bright, n.contrast, n.hi, n.dhash, d.decision, d.committed
                       FROM assets a
                       LEFT JOIN analysis n ON n.id = a.id AND IFNULL(n.checksum,'') = IFNULL(a.checksum,'')
                       LEFT JOIN decisions d ON d.owner = a.owner AND d.id = a.id
                       WHERE a.owner = ?""", (owner,))
        self.all = [_asset(r) for r in rows]
        del rows
        self.all.sort(key=lambda a: a.taken or 0)
        self.by_id = {a.id: a for a in self.all}
        self.dupgroups = {r["dup_id"]: json.loads(r["suggested"] or "[]") for r in db.q("SELECT * FROM dupgroups WHERE owner=?", (owner,))}
        self._stamp = 0
        self._memo: dict = {}
        self._mlock = threading.RLock()
        self._derived = None

    # Änderungen ---------------------------------------------------------------
    def touch(self) -> None:
        with self._mlock:
            self._stamp += 1
            self._memo = {}
            self._derived = None

    def _d(self):
        d = self._derived
        if d is not None:
            return d
        with self._mlock:
            if self._derived is None:
                s = db.user_settings(self.owner)
                live = [a for a in self.all if not a.trashed and a.gone is None]
                pool = [a for a in live
                        if a.decision not in ("keep", "fav")
                        and (s["include_favorites"] or not a.fav)
                        and (s["include_archived"] or not a.archived)
                        and not (a.stack and a.stack_primary == 0 and not a.raw)]
                pending = [a for a in live if a.decision == "trash" and not a.committed]
                self._derived = (s, live, pool, pending)
            return self._derived

    @property
    def settings(self) -> dict:
        return self._d()[0]

    @property
    def live(self) -> list:
        return self._d()[1]

    @property
    def pool(self) -> list:
        return self._d()[2]

    @property
    def pending(self) -> list:
        return self._d()[3]

    def memo(self, key, fn):
        hit = self._memo.get(key)
        if hit is not None:
            return hit
        with self._mlock:  # nur einer rechnet, die anderen warten auf das Ergebnis
            hit = self._memo.get(key)
            if hit is None:
                stamp = self._stamp
                hit = fn()
                if stamp == self._stamp:
                    self._memo[key] = hit
            return hit

    # ------------------------------------------------------------------ Kategorien
    def category(self, name: str) -> list[dict]:
        return self.memo(("cat", name), lambda: self._category(name))

    def _category(self, name: str) -> list[dict]:
        s = self.settings
        imgs = [a for a in self.pool if a.type == "IMAGE"]
        if name == "blurry":
            out = [a for a in imgs if a.sharp is not None and a.sharp < s["blur_threshold"]
                   and (a.bright or 0) >= 25 and (a.contrast or 0) >= 6 and not a.raw]
            return sorted(out, key=lambda a: a.sharp)
        if name == "dark":
            out = [a for a in imgs if a.bright is not None and _misfire(a)]
            return sorted(out, key=lambda a: (a.contrast or 0))
        if name == "screenshots":
            return sorted([a for a in self.pool if a.src[2] == "screen"], key=lambda a: -(a.taken or 0))
        if name == "messenger":
            return sorted([a for a in self.pool if a.src[2] == "messenger"], key=lambda a: -(a.taken or 0))
        if name == "shortvideos":
            lim = s["short_video_s"] * 1000
            return sorted([a for a in self.pool if a.type == "VIDEO" and a.dur and a.dur < lim],
                          key=lambda a: a.dur)
        if name == "large":
            lim = s["large_mb"] * 1024 * 1024
            return sorted([a for a in self.pool if (a.size or 0) >= lim], key=lambda a: -(a.size or 0))
        if name == "raworphans":
            return self.raw_info()["orphans"]
        if name == "noalbum":
            return sorted([a for a in self.live if not a.in_album], key=lambda a: -(a.taken or 0))
        raise KeyError(name)

    # ------------------------------------------------------------------ Duplikate
    def duplicates(self) -> list[dict]:
        return self.memo("dups", self._duplicates)

    def _duplicates(self) -> list[dict]:
        groups = defaultdict(list)
        for a in self.live:
            if a.dup:
                groups[a.dup].append(a)
        out = []
        for did, members in groups.items():
            if len(members) < 2:
                continue
            ids = {a.id for a in members}
            sugg = [i for i in self.dupgroups.get(did, []) if i in ids]
            if not sugg:
                best = max(members, key=lambda a: (bool(a.fav), (a.w or 0) * (a.h or 0), a.size or 0,
                                                   bool(a.city), a.sharp or 0))
                sugg = [best.id]
            members.sort(key=lambda a: (a.id not in sugg, -(a.size or 0)))
            save = sum((a.size or 0) for a in members if a.id not in sugg)
            out.append({"key": did, "assets": members, "keep": sugg, "bytes": save, "taken": members[0].get("taken")})
        out.sort(key=lambda g: -(g["taken"] or 0))
        return out

    # ------------------------------------------------------------------ Serien
    def bursts(self) -> list[dict]:
        return self.memo("bursts", self._bursts)

    def _bursts(self) -> list[dict]:
        s = self.settings
        gap, sim = s["burst_seconds"], s["burst_similarity"]
        imgs = [a for a in self.pool if a.type == "IMAGE" and not a.raw and not a.dup and a.taken]
        imgs.sort(key=lambda a: a.taken)
        groups, cur = [], []
        for a in imgs:
            if cur:
                p = cur[-1]
                dt = a.taken - p.taken
                if a.dhash is not None and p.dhash is not None:
                    ok = dt <= gap and hamming(a.dhash, p.dhash) <= sim
                else:
                    ok = dt <= min(gap, 1.5)
                if ok and len(cur) < 60:
                    cur.append(a)
                    continue
                if len(cur) >= 2:
                    groups.append(cur)
            cur = [a]
        if len(cur) >= 2:
            groups.append(cur)
        out = []
        for g in groups:
            best = max(g, key=lambda a: (bool(a.fav), a.sharp or 0, a.size or 0))
            save = sum((a.size or 0) for a in g if a is not best)
            out.append({"key": g[0]["id"], "assets": g, "keep": [best.id], "bytes": save, "taken": g[0]["taken"]})
        out.sort(key=lambda x: -(x["taken"] or 0))
        return out

    # ------------------------------------------------------------------ RAW + JPG
    def raw_info(self) -> dict:
        return self.memo("raw", self._raw_info)

    def _raw_info(self) -> dict:
        partners = defaultdict(list)  # stem → nicht-RAW-Dateien (auch gelöschte)
        for a in self.all:
            if not a.raw and a.type == "IMAGE":
                partners[a.stem].append(a)
        pairs, orphans, raw_only, raw_bytes = [], [], 0, 0
        for r in self.live:
            if not r.raw:
                continue
            raw_bytes += r.size or 0
            cand = [p for p in partners.get(r.stem, []) if abs((p.taken or 0) - (r.taken or 0)) <= 3]
            alive = [p for p in cand if not p.trashed and p.gone is None and not (p.decision == "trash")]
            if alive:
                j = alive[0]
                stacked = bool(r.stack) and r.stack == j.stack
                pairs.append({"raw": r, "jpg": j, "stacked": stacked})
            elif cand:
                if r.decision not in ("keep", "fav") and (self.settings["include_favorites"] or not r.fav):
                    orphans.append(r)
            else:
                raw_only += 1
        orphans.sort(key=lambda a: -(a.taken or 0))
        return {"pairs": pairs, "unstacked": [p for p in pairs if not p["stacked"]], "orphans": orphans,
                "raw_only": raw_only, "raw_bytes": raw_bytes}

    def raw_partners(self, ids: list[str]) -> list[str]:
        """RAW-Dateien, die zu den angegebenen JPGs gehören (zum Mitlöschen)."""
        want = {}
        for i in ids:
            a = self.by_id.get(i)
            if a and not a.raw:
                want[a.stem] = a
        if not want:
            return []
        out = []
        for r in self.live:
            if r.raw and r.id not in ids and r.decision not in ("keep", "fav") and not r.fav:
                j = want.get(r.stem)
                if j and abs((j.taken or 0) - (r.taken or 0)) <= 3:
                    out.append(r.id)
        return out

    # ------------------------------------------------------------------ Ordnen
    def events(self) -> list[dict]:
        return self.memo("events", self._events)

    def _events(self) -> list[dict]:
        items = [a for a in self.live if a.taken and not (a.decision == "trash")]
        if not items:
            return []
        cities = Counter(a.city for a in items if a.city)
        home = cities.most_common(1)[0][0] if cities else None
        home_country = Counter(a.country for a in items if a.city == home and a.country).most_common(1)
        home_country = home_country[0][0] if home_country else None
        days: dict[str, list] = defaultdict(list)
        for a in items:
            days[day_of(a)].append(a)
        info = []
        for d in sorted(days):
            if d == "0000-00-00":
                continue
            lst = days[d]
            loc = Counter((a.country, a.state, a.city) for a in lst if a.city or a.country)
            dom = loc.most_common(1)[0][0] if loc else None
            away = None if dom is None else (dom[2] != home)
            info.append({"day": d, "items": lst, "dom": dom, "away": away})
        clusters = []
        cur = None
        for di in info:
            dd = date.fromisoformat(di["day"])
            if cur:
                gap = (dd - cur["last"]).days
                same_country = di["dom"] is None or cur["country"] is None or di["dom"][0] == cur["country"]
                merge = False
                if cur["away"] and di["away"] is True and gap <= 2 and same_country:
                    merge = True
                elif cur["away"] and di["away"] is None and gap <= 1:
                    merge = True
                elif cur["away"] is None and di["away"] is None and home is None and gap <= 1 \
                        and len(di["items"]) >= 8 and cur["n_last"] >= 8:
                    merge = True
                if merge:
                    cur["items"].extend(di["items"])
                    cur["last"] = dd
                    cur["n_last"] = len(di["items"])
                    if di["dom"] and not cur["country"]:
                        cur["country"] = di["dom"][0]
                    continue
                clusters.append(cur)
            cur = {"first": dd, "last": dd, "items": list(di["items"]), "away": di["away"], "n_last": len(di["items"]),
                   "country": di["dom"][0] if di["dom"] else None}
        if cur:
            clusters.append(cur)
        out = []
        mn = max(2, int(self.settings["event_min"]))
        for c in clusters:
            lst = c["items"]
            if len(lst) < mn:
                continue
            place = _place_name(lst, home_country)
            when = fmt_range(c["first"].isoformat(), c["last"].isoformat())
            first = c["first"]
            if place:
                album = f"{place} {MONTHS[first.month - 1]} {first.year}" if c["first"] != c["last"] or c["away"] \
                    else f"{place}, {first.day}. {MONTHS[first.month - 1]} {first.year}"
            else:
                album = when
            in_album = sum(1 for a in lst if a.in_album)
            if c["away"] or not place:
                title, subtitle = place or when, when if place else None
            else:  # zu Hause: der Tag ist wichtiger als der Ort
                title, subtitle = f"{WEEKDAYS[first.weekday()]}, {when}" if c["first"] == c["last"] else when, place
            out.append({"key": f"{c['first'].isoformat()}_{c['last'].isoformat()}", "title": title,
                        "subtitle": subtitle, "album": album, "count": len(lst),
                        "photos": sum(1 for a in lst if a.type == "IMAGE"), "videos": sum(1 for a in lst if a.type == "VIDEO"),
                        "in_album": in_album, "away": bool(c["away"]), "days": (c["last"] - c["first"]).days + 1,
                        "cover": _cover(lst)["id"], "ids": [a.id for a in lst], "bytes": sum(a.size or 0 for a in lst),
                        "first": c["first"].isoformat()})
        out.sort(key=lambda e: e["first"], reverse=True)
        return out

    def sources(self) -> list[dict]:
        def build():
            groups = defaultdict(list)
            labels = {}
            for a in self.live:
                if a.decision == "trash":
                    continue
                k, label, kind = a.src
                groups[k].append(a)
                labels[k] = (label, kind)
            out = []
            for k, lst in groups.items():
                lst.sort(key=lambda a: -(a.taken or 0))
                label, kind = labels[k]
                out.append({"key": k, "title": label, "kind": kind, "count": len(lst), "in_album": sum(1 for a in lst if a.in_album),
                            "cover": _cover(lst)["id"], "ids": [a.id for a in lst], "album": label,
                            "bytes": sum(a.size or 0 for a in lst)})
            out.sort(key=lambda g: -g["count"])
            return out
        return self.memo("sources", build)

    def places(self) -> list[dict]:
        def build():
            by_country: dict[str, list] = defaultdict(list)
            for a in self.live:
                if a.country and a.decision != "trash":
                    by_country[a.country].append(a)
            out = []
            for country, lst in by_country.items():
                cities = defaultdict(list)
                for a in lst:
                    cities[a.city or "–"].append(a)
                city_list = []
                for city, cl in cities.items():
                    city_list.append({"key": f"place:{country}:{city}", "title": city if city != "–" else "Ohne Ort",
                                      "count": len(cl), "cover": _cover(cl)["id"], "ids": [a.id for a in cl],
                                      "album": f"{city}" if city != "–" else country, "in_album": sum(1 for a in cl if a.in_album)})
                city_list.sort(key=lambda c: -c["count"])
                years = sorted({day_of(a)[:4] for a in lst})
                out.append({"key": f"place:{country}", "title": country, "count": len(lst), "cover": _cover(lst)["id"],
                            "ids": [a.id for a in lst], "album": country, "cities": city_list,
                            "years": f"{years[0]}–{years[-1]}" if len(years) > 1 else years[0],
                            "in_album": sum(1 for a in lst if a.in_album)})
            out.sort(key=lambda c: -c["count"])
            return out
        return self.memo("places", build)

    def folders(self) -> dict:
        def build():
            dirs = defaultdict(list)
            for a in self.live:
                if a.decision == "trash" or not a.path:
                    continue
                dirs[os.path.dirname(a.path)].append(a)
            if not dirs:
                return {"folders": [], "random": False}
            common = os.path.commonpath(list(dirs)) if len(dirs) > 1 else os.path.dirname(next(iter(dirs)))
            out, hashy = [], 0
            for d, lst in dirs.items():
                rel = os.path.relpath(d, common) if common else d
                if re.search(r"(^|/)[0-9a-f]{2}/[0-9a-f]{2}$", rel):
                    hashy += len(lst)
                name = rel if rel != "." else os.path.basename(d) or d
                out.append({"key": f"dir:{d}", "title": name, "path": d, "count": len(lst), "cover": _cover(lst)["id"],
                            "ids": [a.id for a in lst], "album": os.path.basename(d) or name,
                            "in_album": sum(1 for a in lst if a.in_album)})
            out.sort(key=lambda f: f["title"].lower())
            total = sum(f["count"] for f in out)
            return {"folders": out, "random": total > 0 and hashy / total > 0.5, "root": common}
        return self.memo("folders", build)

    def group_ids(self, kind: str, key: str) -> list[str]:
        if kind == "event":
            for e in self.events():
                if e["key"] == key:
                    return e["ids"]
        elif kind == "source":
            for g in self.sources():
                if g["key"] == key:
                    return g["ids"]
        elif kind == "place":
            for c in self.places():
                if c["key"] == key:
                    return c["ids"]
                for ci in c["cities"]:
                    if ci["key"] == key:
                        return ci["ids"]
        elif kind == "folder":
            for f in self.folders()["folders"]:
                if f["key"] == key:
                    return f["ids"]
        return []

    # ------------------------------------------------------------------ Wischen
    def months(self) -> list[dict]:
        def build():
            m = defaultdict(lambda: [0, 0])
            open_ids = {a.id for a in self.pool if not a.decision}
            for a in self.live:
                k = day_of(a)[:7]
                m[k][0] += 1
                if a.id in open_ids:
                    m[k][1] += 1
            return [{"month": k, "label": month_label(k + "-01") if k != "0000-00" else "Ohne Datum", "total": v[0], "open": v[1]}
                    for k, v in sorted(m.items(), reverse=True)]
        return self.memo("months", build)

    def swipe_queue(self, source: str) -> list[dict]:
        undecided = [a for a in self.pool if not a.decision]
        if source == "all" or not source:
            lst = undecided
        elif source.startswith("month:"):
            mo = source[6:]
            lst = [a for a in undecided if day_of(a)[:7] == mo]
        elif source.startswith("event:"):
            ids = set(self.group_ids("event", source[6:]))
            lst = [a for a in undecided if a.id in ids]
        elif source.startswith("cat:"):
            lst = [a for a in self.category(source[4:]) if not a.decision]
            return lst
        elif source == "random":
            import random
            lst = list(undecided)
            random.shuffle(lst)
            return lst
        else:
            lst = []
        new_first = self.settings.get("swipe_order", "new") != "old"
        return sorted(lst, key=lambda a: a.taken or 0, reverse=new_first)

    # ------------------------------------------------------------------ Übersicht
    def overview(self) -> dict:
        def size(lst):
            return sum(a.size or 0 for a in lst)
        cats = {}
        for c in ("blurry", "dark", "screenshots", "messenger", "shortvideos", "large"):
            lst = self.category(c)
            cats[c] = {"count": len(lst), "bytes": size(lst), "covers": [a.id for a in lst[:4]]}
        d = self.duplicates()
        cats["duplicates"] = {"count": len(d), "items": sum(len(g["assets"]) - len(g["keep"]) for g in d), "bytes": sum(g["bytes"] for g in d),
                              "covers": [g["assets"][0]["id"] for g in d[:4]]}
        b = self.bursts()
        cats["bursts"] = {"count": len(b), "items": sum(len(g["assets"]) - 1 for g in b), "bytes": sum(g["bytes"] for g in b),
                          "covers": [g["keep"][0] for g in b[:4]]}
        r = self.raw_info()
        cats["raw"] = {"count": len(r["orphans"]), "bytes": size(r["orphans"]), "pairs": len(r["pairs"]), "unstacked": len(r["unstacked"]),
                       "raw_only": r["raw_only"], "raw_bytes": r["raw_bytes"], "covers": [a.id for a in r["orphans"][:4]]}
        imgs = [a for a in self.live if a.type == "IMAGE"]
        analyzed = sum(1 for a in imgs if a.bright is not None)
        ev = self.events()
        return {
            "library": {"photos": len(imgs), "videos": sum(1 for a in self.live if a.type == "VIDEO"), "bytes": size(self.live),
                        "noalbum": sum(1 for a in self.live if not a.in_album), "analyzed": analyzed,
                        "reviewed": sum(1 for a in self.live if a.decision in ("keep", "fav")),
                        "first": day_of(self.live[0]) if self.live else None},
            "pending": {"count": len(self.pending), "bytes": size(self.pending)},
            "cats": cats,
            "events": {"count": len(ev), "open": sum(1 for e in ev if e["in_album"] < e["count"] * 0.8),
                       "top": [{k: e[k] for k in ("key", "title", "subtitle", "count", "cover", "in_album")} for e in ev[:6]]},
        }


def _misfire(a: dict) -> bool:
    """Fehlaufnahme: fast schwarz ohne helle Stellen, einfarbig oder völlig überbelichtet."""
    b, c, hi = a.bright, a.contrast or 0, a.hi
    if hi is None:
        hi = b + 2.5 * c
    if b < 30 and hi < 60:          # schwarz (Hosentasche, Objektivdeckel) – Nachtfotos haben helle Lichter
        return True
    if c < 5:                        # einfarbig (Wand, Decke, Finger vor der Linse)
        return True
    return b > 245 and c < 10        # weiß ausgefressen


def _cover(lst: list[dict]) -> dict:
    imgs = [a for a in lst if a.type == "IMAGE" and not a.raw] or lst
    return max(imgs, key=lambda a: (bool(a.fav), (a.sharp or 0) > 60, (a.bright or 0) > 60, a.sharp or 0))


def _place_name(lst: list[dict], home_country: str | None) -> str | None:
    located = [a for a in lst if a.city or a.country]
    if not located:
        return None
    countries = Counter(a.country for a in located if a.country)
    cities = Counter(a.city for a in located if a.city)
    states = Counter(a.state for a in located if a.state)
    n = len(located)
    if cities:
        city, cn = cities.most_common(1)[0]
        if cn >= 0.6 * n:
            country = countries.most_common(1)[0][0] if countries else None
            return city if not country or country == home_country else f"{city}, {country}"
    if states:
        st, sn = states.most_common(1)[0]
        if sn >= 0.7 * n:
            return st
    if countries:
        top = [c for c, _ in countries.most_common(2)]
        if len(top) == 2 and countries[top[1]] >= 0.25 * n:
            return f"{top[0]} & {top[1]}"
        return top[0]
    return None


_libs: dict[str, Library] = {}
_lib_locks: dict[str, threading.Lock] = {}


def _owner_lock(owner: str) -> threading.Lock:
    with _cache_lock:
        return _lib_locks.setdefault(owner, threading.Lock())


def library(owner: str) -> Library:
    """Die Bibliothek eines Benutzers – wird nur einmal geladen (auch wenn viele Anfragen gleichzeitig kommen)."""
    lib = _libs.get(owner)
    if lib is not None and lib.gen == db.version(owner):
        return lib
    with _owner_lock(owner):
        lib = _libs.get(owner)
        if lib is None or lib.gen != db.version(owner):
            _libs.pop(owner, None)
            lib = None  # alten Speicher erst freigeben, dann neu laden
            lib = Library(owner)
            _libs[owner] = lib
        return lib


def update(owner: str, ids, **fields) -> None:
    """Felder von Fotos im Speicher ändern (die Datenbank ändert der Aufrufer)."""
    with _owner_lock(owner):
        lib = _libs.get(owner)
        if lib is None:
            return
        for i in ids:
            a = lib.by_id.get(i)
            if a is not None:
                for k, v in fields.items():
                    setattr(a, k, v)
        lib.touch()


def update_analysis(owner: str, results) -> None:
    """Prüfergebnisse übernehmen: (id, sharp, bright, contrast, hi, dhash)."""
    with _owner_lock(owner):
        lib = _libs.get(owner)
        if lib is None:
            return
        for i, sharp, bright, contrast, hi, dh in results:
            a = lib.by_id.get(i)
            if a is not None:
                a.sharp = None if sharp is None else round(sharp, 1)
                a.bright = None if bright is None else round(bright, 1)
                a.contrast = None if contrast is None else round(contrast, 1)
                a.hi = None if hi is None else round(hi, 1)
                a.dhash = dh
        lib.touch()


def touch(owner: str) -> None:
    lib = _libs.get(owner)
    if lib is not None:
        lib.touch()


def pending_summary(owner: str) -> dict:
    lst = library(owner).pending
    return {"count": len(lst), "bytes": sum(a.size or 0 for a in lst)}
