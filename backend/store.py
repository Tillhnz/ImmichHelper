"""Allgemeine Einstellungen (für alle Benutzer): Immich-Adresse, Push-Nachrichten, Update-Stand.

Liegt als JSON unter IH_STATE_DIR/config.json, atomar geschrieben. Benutzerbezogenes steht in der SQLite-Datenbank.
"""
from __future__ import annotations

import json
import os
import secrets
import threading

from . import db
from .immich import normalize_url

_lock = threading.RLock()
_data: dict | None = None


def _file():
    return db.STATE_DIR / "config.json"


def load() -> dict:
    global _data
    with _lock:
        if _data is None:
            try:
                _data = json.loads(_file().read_text())
            except FileNotFoundError:
                _data = {"secret": secrets.token_hex(32), "settings": {}}
                save()
            except (OSError, ValueError) as e:
                raise SystemExit(f"Konfiguration {_file()} ist nicht lesbar: {e}")
            _data.setdefault("settings", {})
        return _data


def save() -> None:
    with _lock:
        db.STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _file().with_suffix(".tmp")
        with open(tmp, "w") as fh:
            json.dump(_data, fh, indent=1, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, _file())


def reset_cache() -> None:
    global _data
    with _lock:
        _data = None


def settings() -> dict:
    return load()["settings"]


def set_setting(key: str, value) -> None:
    with _lock:
        load()["settings"][key] = value
        save()


def immich_url() -> str:
    return normalize_url(settings().get("immich_url") or os.environ.get("IH_IMMICH_URL", ""))


def immich_public_url() -> str:
    """Adresse für „In Immich öffnen“-Links (z. B. https://fotos.all-heinzen.de), sonst die interne."""
    return normalize_url(settings().get("immich_public_url") or os.environ.get("IH_IMMICH_PUBLIC_URL", "")) or immich_url()
