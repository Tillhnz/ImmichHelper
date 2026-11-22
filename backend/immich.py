"""Schlanker Client für die Immich-API (Immich v1.13x bis v3).

ImmichHelper spricht nur über die offizielle API mit Immich – es fasst nie Dateien auf der NAS an.
So bleibt Immichs Datenbank immer stimmig, und Gelöschtes landet im Immich-Papierkorb.

Unterschiede zwischen den Versionen, die hier ausgeglichen werden:
- Suche: alte Seitennummern (`page`/`nextPage`) und neue Cursor (`cursor`/`nextCursor`, ab v3.2)
- Videolänge: früher Text „0:00:05.123“, ab v3 Millisekunden als Zahl
- Archiv: früher `isArchived`, heute `visibility`
"""
from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = float(os.environ.get("IH_IMMICH_TIMEOUT", "60"))
UA = "ImmichHelper"


class ImmichError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def normalize_url(url: str) -> str:
    """„192.168.1.20:2283“ → „http://192.168.1.20:2283“, ohne „/api“ am Ende."""
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    if url.lower().endswith("/api"):
        url = url[:-4]
    return url


def _ssl_context() -> ssl.SSLContext | None:
    # Eigene Zertifikate im Heimnetz sind häufig – auf Wunsch nicht prüfen (IH_IMMICH_INSECURE=1)
    if os.environ.get("IH_IMMICH_INSECURE", "0") == "1":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return None


def _message(status: int, body: bytes) -> str:
    try:
        data = json.loads(body.decode() or "{}")
        msg = data.get("message")
        if isinstance(msg, list):
            msg = "; ".join(str(m) for m in msg)
        if msg:
            return str(msg)
    except (ValueError, UnicodeDecodeError, AttributeError):
        pass
    return {401: "Nicht angemeldet", 403: "Keine Berechtigung", 404: "Nicht gefunden"}.get(status, f"Immich antwortet mit Fehler {status}")


class Immich:
    """Ein Zugang zu Immich – mit Sitzungs-Token (Anmeldung per Passwort) oder API-Schlüssel."""

    def __init__(self, base: str, token: str | None = None, api_key: str | None = None):
        self.base = normalize_url(base)
        self.token = token
        self.api_key = api_key

    # -----------------------------------------------------------------------
    def _headers(self, extra: dict | None = None) -> dict:
        h = {"User-Agent": UA, "Accept": "application/json"}
        if self.api_key:
            h["x-api-key"] = self.api_key
        elif self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if extra:
            h.update(extra)
        return h

    def url(self, path: str, query: dict | None = None) -> str:
        u = f"{self.base}/api{path}"
        if query:
            u += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        return u

    def open(self, method: str, path: str, *, body=None, query: dict | None = None, headers: dict | None = None,
             timeout: float | None = None):
        """Rohe Antwort (für Bilder/Videos). Der Aufrufer muss sie schließen."""
        if not self.base:
            raise ImmichError(503, "Die Adresse von Immich ist noch nicht eingestellt.")
        data = None
        hdrs = self._headers(headers)
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url(path, query), data=data, method=method, headers=hdrs)
        try:
            return urllib.request.urlopen(req, timeout=timeout or TIMEOUT, context=_ssl_context())
        except urllib.error.HTTPError as e:
            raw = e.read()
            raise ImmichError(e.code, _message(e.code, raw)) from None
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            raise ImmichError(502, f"Immich ist nicht erreichbar ({reason}). Stimmt die Adresse {self.base}?") from None
        except (TimeoutError, OSError) as e:
            raise ImmichError(504, f"Immich antwortet nicht ({e}).") from None

    def call(self, method: str, path: str, *, body=None, query: dict | None = None, timeout: float | None = None):
        with self.open(method, path, body=body, query=query, timeout=timeout) as r:
            raw = r.read()
        if not raw:
            return None
        try:
            return json.loads(raw.decode())
        except (ValueError, UnicodeDecodeError):
            return None

    # -----------------------------------------------------------------------
    # Anmeldung
    # -----------------------------------------------------------------------
    def login(self, email: str, password: str) -> dict:
        r = self.call("POST", "/auth/login", body={"email": email, "password": password})
        if not r or not r.get("accessToken"):
            raise ImmichError(502, "Unerwartete Antwort von Immich bei der Anmeldung.")
        self.token = r["accessToken"]
        return r

    def logout(self) -> None:
        try:
            self.call("POST", "/auth/logout", timeout=10)
        except ImmichError:
            pass

    def me(self) -> dict:
        return self.call("GET", "/users/me")

    def server_version(self) -> str | None:
        try:
            v = self.call("GET", "/server/version", timeout=10)
            return f"{v['major']}.{v['minor']}.{v['patch']}"
        except (ImmichError, KeyError, TypeError):
            return None

    def ping(self) -> bool:
        try:
            r = self.call("GET", "/server/ping", timeout=8)
            return bool(r and r.get("res") == "pong")
        except ImmichError:
            return False

    # -----------------------------------------------------------------------
    # Bibliothek lesen
    # -----------------------------------------------------------------------
    def search_all(self, extra: dict | None = None, size: int = 1000, with_exif: bool = True):
        """Alle Treffer der Metadaten-Suche, Seite für Seite (alte Seitenzahlen und neue Cursor)."""
        body = {"size": size, "withExif": with_exif, **(extra or {})}
        page: int | str | None = 1
        cursor = None
        seen_pages = 0
        while True:
            req = dict(body)
            if cursor:
                req["cursor"] = cursor
            else:
                req["page"] = int(page) if str(page).isdigit() else page
            r = self.call("POST", "/search/metadata", body=req)
            assets = (r or {}).get("assets") or {}
            items = assets.get("items") or []
            yield items
            seen_pages += 1
            if seen_pages > 100000:  # Notbremse
                return
            nxt_cursor = assets.get("nextCursor")
            nxt_page = assets.get("nextPage")
            if nxt_cursor:
                cursor = nxt_cursor
            elif nxt_page:
                cursor = None
                page = nxt_page
            else:
                return
            if not items:
                return

    def duplicates(self) -> list[dict]:
        return self.call("GET", "/duplicates", timeout=180) or []

    def albums(self) -> list[dict]:
        return self.call("GET", "/albums") or []

    def statistics(self) -> dict:
        return self.call("GET", "/assets/statistics") or {}

    # -----------------------------------------------------------------------
    # Ändern
    # -----------------------------------------------------------------------
    def trash(self, ids: list[str]) -> None:
        """In den Immich-Papierkorb (wiederherstellbar, solange der Papierkorb nicht geleert ist)."""
        for chunk in _chunks(ids, 500):
            self.call("DELETE", "/assets", body={"ids": chunk, "force": False})

    def restore(self, ids: list[str]) -> None:
        for chunk in _chunks(ids, 500):
            self.call("POST", "/trash/restore/assets", body={"ids": chunk})

    def empty_trash(self) -> int:
        r = self.call("POST", "/trash/empty") or {}
        return int(r.get("count") or 0)

    def set_favorite(self, ids: list[str], fav: bool) -> None:
        for chunk in _chunks(ids, 500):
            self.call("PUT", "/assets", body={"ids": chunk, "isFavorite": fav})

    def clear_duplicate(self, asset_ids: list[str]) -> None:
        """Bilder aus ihrer Duplikat-Gruppe lösen (so macht es auch Immichs Weboberfläche beim „Behalten“)."""
        for chunk in _chunks(asset_ids, 500):
            self.call("PUT", "/assets", body={"ids": chunk, "duplicateId": None})

    def dismiss_duplicates(self, dup_ids: list[str]) -> None:
        """„Alle behalten“: Gruppe in Immich als erledigt markieren."""
        for d in dup_ids:
            try:
                self.call("DELETE", f"/duplicates/{_uuid(d)}")
            except ImmichError as e:
                if e.status != 404:
                    raise

    def create_album(self, name: str, asset_ids: list[str], description: str | None = None) -> dict:
        first, rest = asset_ids[:500], asset_ids[500:]
        body = {"albumName": name, "assetIds": first}
        if description:
            body["description"] = description
        album = self.call("POST", "/albums", body=body)
        if rest:
            self.add_to_album(album["id"], rest)
        return album

    def add_to_album(self, album_id: str, asset_ids: list[str]) -> int:
        added = 0
        for chunk in _chunks(asset_ids, 500):
            r = self.call("PUT", f"/albums/{_uuid(album_id)}/assets", body={"ids": chunk}) or []
            added += sum(1 for x in r if x.get("success"))
        return added

    def create_stack(self, asset_ids: list[str]) -> dict:
        return self.call("POST", "/stacks", body={"assetIds": asset_ids})


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _uuid(v: str) -> str:
    if not _UUID.match(str(v)):
        raise ImmichError(400, "Ungültige ID")
    return v


def is_uuid(v) -> bool:
    return bool(_UUID.match(str(v)))


def duration_ms(v) -> int | None:
    """Videolänge: Zahl (ms, ab v3) oder Text „H:MM:SS.ffffff“ (bis v2)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = re.match(r"^(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)$", str(v))
    if not m:
        return None
    ms = int((int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) * 1000)
    return ms or None
