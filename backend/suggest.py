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

_cache: dict[str, tuple] = {}
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
class Library:
    """Alle Fotos und Videos eines Benutzers im Speicher – Ergebnisse werden zwischengespeichert."""

    def __init__(self, owner: str):
        self.owner = owner
        self.settings = db.user_settings(owner)
        rows = db.q("""SELECT a.*, n.sharp, n.sharp_g, n.bright, n.contrast, n.dhash, n.hi, d.decision, d.committed
                       FROM assets a
                       LEFT JOIN analysis n ON n.id = a.id AND IFNULL(n.checksum,'') = IFNULL(a.checksum,'')
                       LEFT JOIN decisions d ON d.owner = a.owner AND d.id = a.id
                       WHERE a.owner = ?""", (owner,))
        self.all = [dict(r) for r in rows]
        self.by_id = {a["id"]: a for a in self.all}
        self.live = [a for a in self.all if not a["trashed"] and a["gone"] is None]
        self.live.sort(key=lambda a: a["taken"] or 0)
        s = self.settings
        self.pool = [a for a in self.live
                     if a.get("decision") not in ("keep", "fav")
                     and (s["include_favorites"] or not a["fav"])
                     and (s["include_archived"] or not a["archived"])
                     and not (a.get("stack") and a.get("stack_primary") == 0 and not is_raw(a))]
        self.pending = [a for a in self.live if a.get("decision") == "trash" and not a.get("committed")]
        self._memo: dict = {}
        self.dupgroups = {r["dup_id"]: json.loads(r["suggested"] or "[]") for r in db.q("SELECT * FROM dupgroups WHERE owner=?", (owner,))}

    def memo(self, key, fn):
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]

    # ------------------------------------------------------------------ Kategorien
    def category(self, name: str) -> list[dict]:
        return self.memo(("cat", name), lambda: self._category(name))

    def _category(self, name: str) -> list[dict]:
        s = self.settings
        imgs = [a for a in self.pool if a["type"] == "IMAGE"]
        if name == "blurry":
            out = [a for a in imgs if a.get("sharp") is not None and a["sharp"] < s["blur_threshold"]
                   and (a.get("bright") or 0) >= 25 and (a.get("contrast") or 0) >= 6 and not is_raw(a)]
            return sorted(out, key=lambda a: a["sharp"])
        if name == "dark":
            out = [a for a in imgs if a.get("bright") is not None and _misfire(a)]
            return sorted(out, key=lambda a: (a.get("contrast") or 0))
        if name == "screenshots":
            return sorted([a for a in self.pool if source_of(a)[2] == "screen"], key=lambda a: -(a["taken"] or 0))
        if name == "messenger":
            return sorted([a for a in self.pool if source_of(a)[2] == "messenger"], key=lambda a: -(a["taken"] or 0))
        if name == "shortvideos":
            lim = s["short_video_s"] * 1000
            return sorted([a for a in self.pool if a["type"] == "VIDEO" and a.get("dur") and a["dur"] < lim],
                          key=lambda a: a["dur"])
        if name == "large":
            lim = s["large_mb"] * 1024 * 1024
            return sorted([a for a in self.pool if (a.get("size") or 0) >= lim], key=lambda a: -(a["size"] or 0))
        if name == "raworphans":
            return self.raw_info()["orphans"]
        if name == "noalbum":
            return sorted([a for a in self.live if not a["in_album"]], key=lambda a: -(a["taken"] or 0))
        raise KeyError(name)

    # ------------------------------------------------------------------ Duplikate
    def duplicates(self) -> list[dict]:
        return self.memo("dups", self._duplicates)

    def _duplicates(self) -> list[dict]:
        groups = defaultdict(list)
        for a in self.live:
            if a.get("dup"):
                groups[a["dup"]].append(a)
        out = []
        for did, members in groups.items():
            if len(members) < 2:
                continue
            ids = {a["id"] for a in members}
            sugg = [i for i in self.dupgroups.get(did, []) if i in ids]
            if not sugg:
                best = max(members, key=lambda a: (bool(a["fav"]), (a.get("w") or 0) * (a.get("h") or 0), a.get("size") or 0,
                                                   bool(a.get("city")), a.get("sharp") or 0))
                sugg = [best["id"]]
            members.sort(key=lambda a: (a["id"] not in sugg, -(a.get("size") or 0)))
            save = sum((a.get("size") or 0) for a in members if a["id"] not in sugg)
            out.append({"key": did, "assets": members, "keep": sugg, "bytes": save, "taken": members[0].get("taken")})
        out.sort(key=lambda g: -(g["taken"] or 0))
        return out

    # ------------------------------------------------------------------ Serien
    def bursts(self) -> list[dict]:
        return self.memo("bursts", self._bursts)

    def _bursts(self) -> list[dict]:
        s = self.settings
        gap, sim = s["burst_seconds"], s["burst_similarity"]
        imgs = [a for a in self.pool if a["type"] == "IMAGE" and not is_raw(a) and not a.get("dup") and a.get("taken")]
        imgs.sort(key=lambda a: a["taken"])
        groups, cur = [], []
        for a in imgs:
            if cur:
                p = cur[-1]
                dt = a["taken"] - p["taken"]
                if a.get("dhash") is not None and p.get("dhash") is not None:
                    ok = dt <= gap and hamming(a["dhash"], p["dhash"]) <= sim
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
            best = max(g, key=lambda a: (bool(a["fav"]), a.get("sharp") or 0, a.get("size") or 0))
            save = sum((a.get("size") or 0) for a in g if a is not best)
            out.append({"key": g[0]["id"], "assets": g, "keep": [best["id"]], "bytes": save, "taken": g[0]["taken"]})
        out.sort(key=lambda x: -(x["taken"] or 0))
        return out

    # ------------------------------------------------------------------ RAW + JPG
    def raw_info(self) -> dict:
        return self.memo("raw", self._raw_info)

    def _raw_info(self) -> dict:
        partners = defaultdict(list)  # stem → nicht-RAW-Dateien (auch gelöschte)
        for a in self.all:
            if not is_raw(a) and a["type"] == "IMAGE":
                partners[stem(a["name"])].append(a)
        pairs, orphans, raw_only, raw_bytes = [], [], 0, 0
        for r in self.live:
            if not is_raw(r):
                continue
            raw_bytes += r.get("size") or 0
            cand = [p for p in partners.get(stem(r["name"]), []) if abs((p.get("taken") or 0) - (r.get("taken") or 0)) <= 3]
            alive = [p for p in cand if not p["trashed"] and p["gone"] is None and not (p.get("decision") == "trash")]
            if alive:
                j = alive[0]
                stacked = bool(r.get("stack")) and r.get("stack") == j.get("stack")
                pairs.append({"raw": r, "jpg": j, "stacked": stacked})
            elif cand:
                if r.get("decision") not in ("keep", "fav") and (self.settings["include_favorites"] or not r["fav"]):
                    orphans.append(r)
            else:
                raw_only += 1
        orphans.sort(key=lambda a: -(a["taken"] or 0))
        return {"pairs": pairs, "unstacked": [p for p in pairs if not p["stacked"]], "orphans": orphans,
                "raw_only": raw_only, "raw_bytes": raw_bytes}

    def raw_partners(self, ids: list[str]) -> list[str]:
        """RAW-Dateien, die zu den angegebenen JPGs gehören (zum Mitlöschen)."""
        want = {}
        for i in ids:
            a = self.by_id.get(i)
            if a and not is_raw(a):
                want[stem(a["name"])] = a
        if not want:
            return []
        out = []
        for r in self.live:
            if is_raw(r) and r["id"] not in ids and r.get("decision") not in ("keep", "fav") and not r["fav"]:
                j = want.get(stem(r["name"]))
                if j and abs((j.get("taken") or 0) - (r.get("taken") or 0)) <= 3:
                    out.append(r["id"])
        return out

    # ------------------------------------------------------------------ Ordnen
    def events(self) -> list[dict]:
        return self.memo("events", self._events)

    def _events(self) -> list[dict]:
        items = [a for a in self.live if a.get("taken") and not (a.get("decision") == "trash")]
        if not items:
            return []
        cities = Counter(a["city"] for a in items if a.get("city"))
        home = cities.most_common(1)[0][0] if cities else None
        home_country = Counter(a["country"] for a in items if a.get("city") == home and a.get("country")).most_common(1)
        home_country = home_country[0][0] if home_country else None
        days: dict[str, list] = defaultdict(list)
        for a in items:
            days[day_of(a)].append(a)
        info = []
        for d in sorted(days):
            if d == "0000-00-00":
                continue
            lst = days[d]
            loc = Counter((a.get("country"), a.get("state"), a.get("city")) for a in lst if a.get("city") or a.get("country"))
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
            in_album = sum(1 for a in lst if a["in_album"])
            if c["away"] or not place:
                title, subtitle = place or when, when if place else None
            else:  # zu Hause: der Tag ist wichtiger als der Ort
                title, subtitle = f"{WEEKDAYS[first.weekday()]}, {when}" if c["first"] == c["last"] else when, place
            out.append({"key": f"{c['first'].isoformat()}_{c['last'].isoformat()}", "title": title,
                        "subtitle": subtitle, "album": album, "count": len(lst),
                        "photos": sum(1 for a in lst if a["type"] == "IMAGE"), "videos": sum(1 for a in lst if a["type"] == "VIDEO"),
                        "in_album": in_album, "away": bool(c["away"]), "days": (c["last"] - c["first"]).days + 1,
                        "cover": _cover(lst)["id"], "ids": [a["id"] for a in lst], "bytes": sum(a.get("size") or 0 for a in lst),
                        "first": c["first"].isoformat()})
        out.sort(key=lambda e: e["first"], reverse=True)
        return out

    def sources(self) -> list[dict]:
        def build():
            groups = defaultdict(list)
            labels = {}
            for a in self.live:
                if a.get("decision") == "trash":
                    continue
                k, label, kind = source_of(a)
                groups[k].append(a)
                labels[k] = (label, kind)
            out = []
            for k, lst in groups.items():
                lst.sort(key=lambda a: -(a["taken"] or 0))
                label, kind = labels[k]
                out.append({"key": k, "title": label, "kind": kind, "count": len(lst), "in_album": sum(1 for a in lst if a["in_album"]),
                            "cover": _cover(lst)["id"], "ids": [a["id"] for a in lst], "album": label,
                            "bytes": sum(a.get("size") or 0 for a in lst)})
            out.sort(key=lambda g: -g["count"])
            return out
        return self.memo("sources", build)

    def places(self) -> list[dict]:
        def build():
            by_country: dict[str, list] = defaultdict(list)
            for a in self.live:
                if a.get("country") and a.get("decision") != "trash":
                    by_country[a["country"]].append(a)
            out = []
            for country, lst in by_country.items():
                cities = defaultdict(list)
                for a in lst:
                    cities[a.get("city") or "–"].append(a)
                city_list = []
                for city, cl in cities.items():
                    city_list.append({"key": f"place:{country}:{city}", "title": city if city != "–" else "Ohne Ort",
                                      "count": len(cl), "cover": _cover(cl)["id"], "ids": [a["id"] for a in cl],
                                      "album": f"{city}" if city != "–" else country, "in_album": sum(1 for a in cl if a["in_album"])})
                city_list.sort(key=lambda c: -c["count"])
                years = sorted({day_of(a)[:4] for a in lst})
                out.append({"key": f"place:{country}", "title": country, "count": len(lst), "cover": _cover(lst)["id"],
                            "ids": [a["id"] for a in lst], "album": country, "cities": city_list,
                            "years": f"{years[0]}–{years[-1]}" if len(years) > 1 else years[0],
                            "in_album": sum(1 for a in lst if a["in_album"])})
            out.sort(key=lambda c: -c["count"])
            return out
        return self.memo("places", build)

    def folders(self) -> dict:
        def build():
            dirs = defaultdict(list)
            for a in self.live:
                if a.get("decision") == "trash" or not a.get("path"):
                    continue
                dirs[os.path.dirname(a["path"])].append(a)
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
                            "ids": [a["id"] for a in lst], "album": os.path.basename(d) or name,
                            "in_album": sum(1 for a in lst if a["in_album"])})
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
            open_ids = {a["id"] for a in self.pool if not a.get("decision")}
            for a in self.live:
                k = day_of(a)[:7]
                m[k][0] += 1
                if a["id"] in open_ids:
                    m[k][1] += 1
            return [{"month": k, "label": month_label(k + "-01") if k != "0000-00" else "Ohne Datum", "total": v[0], "open": v[1]}
                    for k, v in sorted(m.items(), reverse=True)]
        return self.memo("months", build)

    def swipe_queue(self, source: str) -> list[dict]:
        undecided = [a for a in self.pool if not a.get("decision")]
        if source == "all" or not source:
            lst = undecided
        elif source.startswith("month:"):
            mo = source[6:]
            lst = [a for a in undecided if day_of(a)[:7] == mo]
        elif source.startswith("event:"):
            ids = set(self.group_ids("event", source[6:]))
            lst = [a for a in undecided if a["id"] in ids]
        elif source.startswith("cat:"):
            lst = [a for a in self.category(source[4:]) if not a.get("decision")]
            return lst
        elif source == "random":
            import random
            lst = list(undecided)
            random.shuffle(lst)
            return lst
        else:
            lst = []
        new_first = self.settings.get("swipe_order", "new") != "old"
        return sorted(lst, key=lambda a: a.get("taken") or 0, reverse=new_first)

    # ------------------------------------------------------------------ Übersicht
    def overview(self) -> dict:
        def size(lst):
            return sum(a.get("size") or 0 for a in lst)
        cats = {}
        for c in ("blurry", "dark", "screenshots", "messenger", "shortvideos", "large"):
            lst = self.category(c)
            cats[c] = {"count": len(lst), "bytes": size(lst), "covers": [a["id"] for a in lst[:4]]}
        d = self.duplicates()
        cats["duplicates"] = {"count": len(d), "items": sum(len(g["assets"]) - len(g["keep"]) for g in d), "bytes": sum(g["bytes"] for g in d),
                              "covers": [g["assets"][0]["id"] for g in d[:4]]}
        b = self.bursts()
        cats["bursts"] = {"count": len(b), "items": sum(len(g["assets"]) - 1 for g in b), "bytes": sum(g["bytes"] for g in b),
                          "covers": [g["keep"][0] for g in b[:4]]}
        r = self.raw_info()
        cats["raw"] = {"count": len(r["orphans"]), "bytes": size(r["orphans"]), "pairs": len(r["pairs"]), "unstacked": len(r["unstacked"]),
                       "raw_only": r["raw_only"], "raw_bytes": r["raw_bytes"], "covers": [a["id"] for a in r["orphans"][:4]]}
        imgs = [a for a in self.live if a["type"] == "IMAGE"]
        analyzed = sum(1 for a in imgs if a.get("bright") is not None)
        ev = self.events()
        return {
            "library": {"photos": len(imgs), "videos": sum(1 for a in self.live if a["type"] == "VIDEO"), "bytes": size(self.live),
                        "noalbum": sum(1 for a in self.live if not a["in_album"]), "analyzed": analyzed,
                        "reviewed": sum(1 for a in self.live if a.get("decision") in ("keep", "fav")),
                        "first": day_of(self.live[0]) if self.live else None},
            "pending": {"count": len(self.pending), "bytes": size(self.pending)},
            "cats": cats,
            "events": {"count": len(ev), "open": sum(1 for e in ev if e["in_album"] < e["count"] * 0.8),
                       "top": [{k: e[k] for k in ("key", "title", "subtitle", "count", "cover", "in_album")} for e in ev[:6]]},
        }


def _misfire(a: dict) -> bool:
    """Fehlaufnahme: fast schwarz ohne helle Stellen, einfarbig oder völlig überbelichtet."""
    b, c, hi = a["bright"], a.get("contrast") or 0, a.get("hi")
    if hi is None:
        hi = b + 2.5 * c
    if b < 30 and hi < 60:          # schwarz (Hosentasche, Objektivdeckel) – Nachtfotos haben helle Lichter
        return True
    if c < 5:                        # einfarbig (Wand, Decke, Finger vor der Linse)
        return True
    return b > 245 and c < 10        # weiß ausgefressen


def _cover(lst: list[dict]) -> dict:
    imgs = [a for a in lst if a["type"] == "IMAGE" and not is_raw(a)] or lst
    return max(imgs, key=lambda a: (bool(a["fav"]), (a.get("sharp") or 0) > 60, (a.get("bright") or 0) > 60, a.get("sharp") or 0))


def _place_name(lst: list[dict], home_country: str | None) -> str | None:
    located = [a for a in lst if a.get("city") or a.get("country")]
    if not located:
        return None
    countries = Counter(a.get("country") for a in located if a.get("country"))
    cities = Counter(a.get("city") for a in located if a.get("city"))
    states = Counter(a.get("state") for a in located if a.get("state"))
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


def library(owner: str) -> Library:
    key = (db.version(owner),)
    with _cache_lock:
        hit = _cache.get(owner)
        if hit and hit[0] == key:
            return hit[1]
    lib = Library(owner)
    with _cache_lock:
        _cache[owner] = (key, lib)
    return lib
