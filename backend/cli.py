"""Hilfsbefehle im Container: immichhelper status | url <adresse> | logout-all"""
from __future__ import annotations

import sys
import time

from . import db, store
from .immich import Immich, normalize_url


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    if cmd == "status":
        url = store.immich_url()
        print(f"Immich-Adresse: {url or '– (noch nicht eingestellt)'}")
        if url:
            cli = Immich(url)
            print(f"Erreichbar:     {'ja' if cli.ping() else 'NEIN'}" + (f" (Immich {cli.server_version()})" if cli.ping() else ""))
        rows = db.q("SELECT m.name, m.last_sync, (SELECT COUNT(*) FROM assets a WHERE a.owner=m.owner AND a.gone IS NULL AND a.trashed=0) n FROM user_meta m")
        for r in rows:
            when = time.strftime("%d.%m.%Y %H:%M", time.localtime(r["last_sync"])) if r["last_sync"] else "noch nie"
            print(f"Benutzer:       {r['name']} – {r['n']} Fotos/Videos, zuletzt eingelesen {when}")
        return 0
    if cmd == "url":
        if len(argv) < 2:
            print("Aufruf: immichhelper url http://<IP>:2283", file=sys.stderr)
            return 2
        url = normalize_url(argv[1])
        if not Immich(url).ping():
            print(f"Warnung: Unter {url} antwortet gerade kein Immich – trotzdem gespeichert.", file=sys.stderr)
        store.set_setting("immich_url", url)
        print(f"Immich-Adresse gespeichert: {url}")
        return 0
    if cmd == "logout-all":
        n = db.run("DELETE FROM sessions")
        print(f"{n} Anmeldungen beendet.")
        return 0
    print("Unbekannter Befehl. Möglich: status, url <adresse>, logout-all", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
