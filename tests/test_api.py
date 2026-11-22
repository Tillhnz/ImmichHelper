"""Tests gegen ein Schein-Immich (tests/fake_immich.py): echter Server, echte HTTP-Anfragen."""
from __future__ import annotations

import http.cookiejar
import importlib
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def serve(app, port):
    import uvicorn
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="on")
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return srv
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("Server startet nicht")


class Client:
    def __init__(self, base):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def req(self, method, path, body=None, headers=None, raw=False, csrf=True):
        h = {"X-ImmichHelper": "1"} if csrf else {}
        h.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with self.op.open(r, timeout=30) as resp:
                content = resp.read()
                return (resp.status, content, resp.headers) if raw else (resp.status, json.loads(content or b"{}"))
        except urllib.error.HTTPError as e:
            content = e.read()
            return (e.code, content, e.headers) if raw else (e.code, json.loads(content or b"{}"))

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.req("POST", path, body if body is not None else {}, **kw)


@pytest.fixture(scope="module", params=[False, True], ids=["immich-v2", "immich-v3"])
def env(request):
    os.environ["FAKE_CURSOR"] = "1" if request.param else "0"
    import tests.fake_immich as fake
    importlib.reload(fake)
    iport = free_port()
    isrv = serve(fake.app, iport)
    state = tempfile.mkdtemp()
    os.environ["IH_STATE_DIR"] = state
    os.environ["IH_BACKGROUND"] = "0"
    os.environ.pop("IH_IMMICH_URL", None)
    for m in [m for m in list(sys.modules) if m.startswith("backend")]:
        del sys.modules[m]
    from backend import app as appmod
    port = free_port()
    srv = serve(appmod.app, port)
    yield {"fake": fake, "immich": f"http://127.0.0.1:{iport}", "base": f"http://127.0.0.1:{port}"}
    srv.should_exit = True
    isrv.should_exit = True
    time.sleep(0.3)


def wait_sync(c: Client, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        _, st = c.get("/api/status")
        if st["job"] and st["job"]["state"] != "running":
            assert st["job"]["state"] == "done", st
            return st
        time.sleep(0.2)
    raise AssertionError("Einlesen dauert zu lange")


def test_flow(env):
    fake = env["fake"]
    c = Client(env["base"])
    # Einrichtung
    code, s = c.get("/api/setup")
    assert code == 200 and not s["configured"]
    code, r = c.post("/api/setup", {"url": "http://127.0.0.1:1"})
    assert code == 400
    code, r = c.post("/api/setup", {"url": env["immich"] + "/api"})
    assert code == 200, r
    assert c.get("/api/setup")[1]["immich_url"] == env["immich"]
    # Ohne Anmeldung kein Zugriff, ohne CSRF-Header keine Änderungen
    assert c.get("/api/overview")[0] == 401
    assert c.post("/api/login", {"email": "till@example.com", "password": "test"}, csrf=False)[0] == 403
    assert c.post("/api/login", {"email": "till@example.com", "password": "falsch"})[0] == 401
    code, r = c.post("/api/login", {"email": "till@example.com", "password": "test"})
    assert code == 200, r
    _, me = c.get("/api/me")
    assert me["user"]["name"] == "Till" and me["user"]["admin"]
    st = wait_sync(c)
    assert st["last_sync"]

    _, ov = c.get("/api/overview")
    lib = ov["library"]
    total_visible = sum(1 for a in fake.LIB.assets.values() if a["id"] not in fake.LIB.trash)
    assert lib["photos"] + lib["videos"] == total_visible
    assert lib["analyzed"] == lib["photos"]
    cats = ov["cats"]
    assert cats["blurry"]["count"] >= 4          # 4 unscharfe + das unscharfe Serienfoto
    assert cats["dark"]["count"] == 4            # 3 schwarze + 1 einfarbiges
    assert cats["screenshots"]["count"] == 6
    assert cats["messenger"]["count"] == 9       # 8 WhatsApp + 1 Telegram
    assert cats["shortvideos"]["count"] == 2     # Textdauer (v2) und Millisekunden (v3)
    assert cats["large"]["count"] == 1
    assert cats["duplicates"]["count"] == 1
    assert cats["bursts"]["count"] >= 1
    assert cats["raw"]["pairs"] == 18 and cats["raw"]["unstacked"] == 18

    # Messenger: Quellen als Liste von [Name, Anzahl] (die Oberfläche erwartet eine Liste)
    _, ms = c.get("/api/cat/messenger")
    assert ms["sources"] and all(isinstance(x, list) and len(x) == 2 for x in ms["sources"])

    # Favorit und archiviertes Foto
    _, bl = c.get("/api/cat/blurry?limit=500")
    names = {a["name"] for a in bl["items"]}
    assert "PXL_20251010_101010.jpg" not in names   # Favorit nie vorschlagen
    assert "PXL_20250202_020202.jpg" in names       # archiviert ja (Standard)

    # Serie: das unscharfe Bild darf nicht das behaltene sein
    _, bu = c.get("/api/bursts")
    g = next(g for g in bu["items"] if len(g["assets"]) == 5)
    keep = g["keep"][0]
    assert next(a for a in g["assets"] if a["id"] == keep)["name"] != "PXL_20250312_173002.jpg"

    # Ereignisse: Bali-Reise als ein Ereignis, Geburtstag als eigener Tag
    _, ev = c.get("/api/organize/events")
    titles = [e["title"] for e in ev["items"]]
    bali = next(e for e in ev["items"] if "Bali" in e["title"] or "Ubud" in e["title"] or "Indonesia" in e["title"])
    assert bali["days"] == 6 and bali["count"] >= 60, titles
    assert any(e["key"].startswith("2025-06-14") for e in ev["items"]), titles
    _, src = c.get("/api/organize/sources")
    keys = {s["key"] for s in src["items"]}
    assert {"msg:whatsapp", "screen:shot", "cam:fujifilm x-s20", "cam:google pixel 8"} <= keys

    # Album aus Ereignis anlegen
    code, r = c.post("/api/albums", {"kind": "event", "key": bali["key"], "name": "Bali März 2025"})
    assert code == 200 and r["added"] == bali["count"], r
    assert any(a["albumName"] == "Bali März 2025" for a in fake.LIB.albums.values())

    # Wischen: vormerken, Favorit, zurücknehmen, dann löschen
    _, q = c.get("/api/swipe?source=all&limit=5")
    a1, a2, a3 = q["items"][0], q["items"][1], q["items"][2]
    assert c.post("/api/marks", {"ids": [a1["id"]], "decision": "trash"})[1]["pending"]["count"] == 1
    c.post("/api/marks", {"ids": [a2["id"]], "decision": "fav"})
    assert fake.LIB.assets[a2["id"]]["isFavorite"] is True
    c.post("/api/marks", {"ids": [a3["id"]], "decision": "keep"})
    _, q2 = c.get("/api/swipe?source=all&limit=5")
    assert a1["id"] not in [x["id"] for x in q2["items"]]
    c.post("/api/marks", {"ids": [a2["id"]], "decision": "none"})
    assert fake.LIB.assets[a2["id"]]["isFavorite"] is False
    code, r = c.post("/api/marks/commit")
    assert code == 200 and r["count"] == 1
    assert a1["id"] in fake.LIB.trash

    # JPG löschen → RAF wird mitgelöscht
    jpg = next(a for a in fake.LIB.assets.values() if a["originalFileName"] == "DSCF1000.JPG")
    raf = next(a for a in fake.LIB.assets.values() if a["originalFileName"] == "DSCF1000.RAF")
    code, r = c.post("/api/trash", {"ids": [jpg["id"]], "label": "Test"})
    assert r["count"] == 2 and r["raw"] == 1
    assert raf["id"] in fake.LIB.trash
    # … und lässt sich wiederherstellen
    _, hist = c.get("/api/history")
    lid = next(h for h in hist["items"] if h["label"] == "Test")["id"]
    assert c.post(f"/api/history/{lid}/restore")[0] == 200
    assert raf["id"] not in fake.LIB.trash and jpg["id"] not in fake.LIB.trash

    # Nur das JPG löschen (ohne RAW) → RAW ohne JPG wird erkannt
    c.post("/api/trash", {"ids": [jpg["id"]], "label": "nur JPG", "raw_follow": False})
    _, rw = c.get("/api/raw")
    assert rw["orphans"] == 1
    _, orph = c.get("/api/cat/raworphans")
    assert orph["items"][0]["id"] == raf["id"]

    # Stapeln
    code, r = c.post("/api/stack")
    assert code == 200 and r["done"] == 17
    assert c.get("/api/raw")[1]["unstacked"] == 0

    # Duplikate nach Vorschlag aufräumen
    _, du = c.get("/api/duplicates")
    grp = du["items"][0]
    drop = [a["id"] for a in grp["assets"] if a["id"] not in grp["keep"]]
    code, r = c.post("/api/resolve", {"kind": "duplicates", "keep": grp["keep"], "trash": drop})
    assert code == 200 and r["count"] == 1
    assert fake.LIB.assets[grp["keep"][0]]["duplicateId"] is None
    assert c.get("/api/duplicates")[1]["total"] == 0

    # Neu einlesen: im Immich wiederhergestellte Fotos tauchen wieder auf
    fake.LIB.trash.discard(a1["id"])
    c.post("/api/sync")
    wait_sync(c)
    _, ov2 = c.get("/api/overview")
    assert ov2["library"]["photos"] + ov2["library"]["videos"] == sum(1 for a in fake.LIB.assets.values() if a["id"] not in fake.LIB.trash)

    # Vorschaubilder: das erste Mal von Immich, danach aus dem Zwischenspeicher (Immich wird nicht erneut gefragt)
    code, body, hdr = c.get(f"/api/thumb/{grp['keep'][0]}", raw=True)
    assert code == 200 and hdr["Content-Type"].startswith("image/") and len(body) > 100
    before = fake.LIB.thumb_calls
    code, body2, hdr2 = c.get(f"/api/thumb/{grp['keep'][0]}", raw=True)
    assert body2 == body and fake.LIB.thumb_calls == before and hdr2["Server-Timing"].startswith("mem")
    # Die von der Bildprüfung geladenen großen Vorschauen liegen schon bereit
    code, _, hdr3 = c.get(f"/api/thumb/{grp['keep'][0]}?size=preview", raw=True)
    assert code == 200 and hdr3["Server-Timing"].split(";")[0] in ("mem", "disk")
    # Wischen lädt die nächsten Bilder vorab
    _, q3 = c.get("/api/swipe?source=all&limit=3")
    time.sleep(1.0)
    before = fake.LIB.thumb_calls
    for it in q3["items"]:
        assert c.get(f"/api/thumb/{it['id']}", raw=True)[0] == 200
    assert fake.LIB.thumb_calls == before
    vid = next(a for a in fake.LIB.assets.values() if a["type"] == "VIDEO")
    code, body, hdr = c.get(f"/api/video/{vid['id']}", headers={"Range": "bytes=0-99"}, raw=True)
    assert code == 206 and len(body) == 100 and hdr["Content-Range"].startswith("bytes 0-99/")
    assert c.get("/api/thumb/..%2F..%2Fetc%2Fpasswd", raw=True)[0] in (400, 404)

    # Einstellungen
    code, r = c.req("PUT", "/api/settings", {"blur_threshold": 0, "unbekannt": 1})
    assert r["settings"]["blur_threshold"] == 0 and "unbekannt" not in r["settings"]
    assert c.get("/api/cat/blurry")[1]["total"] == 0 < bl["total"]

    # Selbsttest
    code, d = c.get("/api/system/diag")
    assert code == 200 and all(ch["ok"] for ch in d["checks"]) and len(d["checks"]) == 3 and d["assets"] > 100

    # Abmelden
    c.post("/api/logout")
    assert c.get("/api/overview")[0] == 401


def test_api_key_login(env):
    c = Client(env["base"])
    assert c.post("/api/login", {"api_key": "falsch"})[0] == 401
    code, r = c.post("/api/login", {"api_key": "test-api-key"})
    assert code == 200
    assert c.get("/api/me")[1]["user"]["kind"] == "key"


def test_analyze_detects_blur():
    from PIL import Image, ImageDraw, ImageFilter
    from backend.analyze import analyze, hamming
    import io
    img = Image.new("RGB", (1440, 1080), (120, 130, 140))
    d = ImageDraw.Draw(img)
    import random
    r = random.Random(1)
    for _ in range(200):
        x, y = r.randint(0, 1440), r.randint(0, 1080)
        d.rectangle((x, y, x + r.randint(5, 80), y + r.randint(5, 80)), fill=tuple(r.randint(0, 255) for _ in range(3)))

    def enc(i):
        b = io.BytesIO()
        i.save(b, "JPEG", quality=85)
        return b.getvalue()
    sharp = analyze(enc(img))
    blurry = analyze(enc(img.filter(ImageFilter.GaussianBlur(8))))
    assert sharp["sharp"] > 100 > blurry["sharp"] * 3
    assert hamming(sharp["dhash"], blurry["dhash"]) <= 10
    dark = analyze(enc(Image.new("RGB", (800, 600), (5, 5, 5))))
    assert dark["bright"] < 10 and dark["contrast"] < 3
