"""Update-Wächter: meldet per Push (ntfy), sobald auf GitHub eine neue Version von ImmichHelper bereitliegt.

Wie bei den anderen Helpern: Alle 6 Stunden wird verglichen, welcher Stand installiert ist (git-Commit in
/opt/immichhelper) und was auf GitHub liegt. Jede neue Version wird genau einmal gemeldet. Enthält sie Paket- oder
Sicherheitsupdates (z. B. von Dependabot), kommt die Meldung mit hoher Priorität.

Gezählt werden Commits, nicht nur die Datei VERSION – sonst fielen automatisch übernommene
Dependabot-Updates nicht auf, weil die die Versionsnummer nicht ändern.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from . import store

log = logging.getLogger("immichhelper.updatewatch")
BASE = Path(__file__).resolve().parent.parent
REPO = os.environ.get("IH_REPO", "Tillhnz/ImmichHelper")
BRANCH = os.environ.get("IH_BRANCH", "main")
CHECK_EVERY_S = 6 * 3600
SECURITY = re.compile(r"\b(bump|sicherheit|security|cve-|lücke|vulnerab|dependabot)\b", re.I)

_status: dict = {"checked": 0.0, "behind": 0, "changes": [], "latest_version": None, "error": None}
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Einstellungen für Push-Nachrichten (in der Oberfläche änderbar, sonst aus /etc/immichhelper.env)
# ---------------------------------------------------------------------------
def ntfy_settings() -> dict:
    saved = store.settings().get("ntfy") or {}
    return {
        "url": (saved.get("url") or os.environ.get("IH_NTFY_URL") or "https://ntfy.sh").rstrip("/"),
        "topic": saved.get("topic", os.environ.get("IH_NTFY_TOPIC", "")) or "",
        "token": saved.get("token", os.environ.get("IH_NTFY_TOKEN", "")) or "",
        "notify": bool(saved.get("notify", os.environ.get("IH_UPDATE_NOTIFY", "1") == "1")),
        "click": saved.get("click") or os.environ.get("IH_PUBLIC_URL", ""),
    }


def push(title: str, message: str, priority: int = 3, tags=("package",)) -> None:
    s = ntfy_settings()
    if not s["topic"]:
        raise RuntimeError("Kein ntfy-Thema eingestellt.")
    payload = {"topic": s["topic"], "title": title, "message": message, "priority": priority, "tags": list(tags)}
    if s["click"]:
        payload["click"] = s["click"].rstrip("/") + "/#/settings"
    headers = {"Content-Type": "application/json", "User-Agent": "ImmichHelper"}
    if s["token"]:
        headers["Authorization"] = f"Bearer {s['token']}"
    req = urllib.request.Request(s["url"], data=json.dumps(payload).encode(), method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=15) as r:
        r.read()


# ---------------------------------------------------------------------------
# Installierter Stand und Stand auf GitHub
# ---------------------------------------------------------------------------
def installed_commit() -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(BASE), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        sha = r.stdout.strip()
        return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None
    except (OSError, subprocess.SubprocessError):
        return None


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "ImmichHelper"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())


def check(force: bool = False) -> dict:
    """Fragt GitHub (höchstens alle 6 Stunden, außer force). Gibt den Status zurück."""
    with _lock:
        if not force and time.time() - _status["checked"] < CHECK_EVERY_S:
            return dict(_status)
        _status["checked"] = time.time()
        mine = installed_commit()
        try:
            commits = _get_json(f"https://api.github.com/repos/{REPO}/commits?sha={BRANCH}&per_page=50")
            changes = []
            found = False
            for c in commits:
                if mine and c.get("sha") == mine:
                    found = True
                    break
                subject = (c.get("commit", {}).get("message") or "").split("\n", 1)[0].strip()
                changes.append({"sha": c.get("sha", "")[:7], "subject": subject,
                                "date": c.get("commit", {}).get("committer", {}).get("date")})
            if not mine:  # keine git-Installation (z. B. Entwicklung): nur die Versionsnummer vergleichen
                changes = []
            _status.update(behind=len(changes), changes=changes, more=bool(mine and not found and changes),
                           head=(commits[0].get("sha", "")[:7] if commits else None), error=None)
        except Exception as e:  # noqa: BLE001 – offline o. ä.: einfach später noch einmal
            _status.update(error=str(e)[:200])
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/VERSION", headers={"User-Agent": "ImmichHelper"}), timeout=10) as r:
                _status["latest_version"] = r.read().decode().strip()[:20] or None
        except Exception:  # noqa: BLE001
            pass
        _status["installed"] = (mine or "")[:7] or None
        return dict(_status)


def describe(changes: list[dict]) -> tuple[bool, str]:
    subjects = [c["subject"] for c in changes]
    sec = any(SECURITY.search(s) for s in subjects)
    lines = "\n".join(f"• {s}" for s in subjects[:8]) + (f"\n… und {len(subjects) - 8} weitere" if len(subjects) > 8 else "")
    return sec, lines


def notify_once() -> bool:
    """Meldet eine neue Version genau einmal. Gibt True zurück, wenn gepusht wurde."""
    s = ntfy_settings()
    if not s["notify"] or not s["topic"]:
        return False
    st = check()
    if not st.get("behind") or not st.get("changes"):
        return False
    key = st["changes"][0]["sha"]
    if store.settings().get("update_notified") == key:
        return False
    sec, lines = describe(st["changes"])
    n = st["behind"]
    title = ("Sicherheitsupdate" if sec else "Neue Version") + " für ImmichHelper verfügbar"
    version = f" (Version {st['latest_version']})" if st.get("latest_version") else ""
    body = (f"{n}{'+' if st.get('more') else ''} {'Änderung' if n == 1 else 'Änderungen'}{version}:\n{lines}\n\n"
            "Einspielen: ImmichHelper → Einstellungen → System → Aktualisieren.")
    push(title, body, priority=4 if sec else 3, tags=("warning", "package") if sec else ("package",))
    store.set_setting("update_notified", key)
    return True


def start_background() -> None:
    def loop():
        time.sleep(120)  # nach dem Start erst einmal in Ruhe lassen
        while True:
            try:
                notify_once()
            except Exception as e:  # noqa: BLE001
                log.warning("Update-Meldung nicht möglich: %s", e)
            time.sleep(CHECK_EVERY_S)
    threading.Thread(target=loop, daemon=True, name="updatewatch").start()
