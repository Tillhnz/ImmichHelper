"""Ein kleines Schein-Immich für Tests und zum Ausprobieren ohne echten Server.

Start:  python -m tests.fake_immich  (Port 2283, Anmeldung till@example.com / test)
Enthält eine Beispiel-Bibliothek: Alltag in Köln, eine Bali-Reise, Serien, unscharfe und schwarze Bilder,
Screenshots, WhatsApp-Bilder, Fujifilm RAF+JPG-Paare, kurze Videos und eine Duplikat-Gruppe.
"""
from __future__ import annotations

import base64
import copy
import glob
import io
import os
import random
import uuid
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFilter
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

EMAIL, PASSWORD = "till@example.com", "test"
API_KEY = "test-api-key"
USER_ID = "11111111-1111-4111-8111-111111111111"


def _uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


class Lib:
    def __init__(self, cursor_api: bool = False, seed: int = 7):
        self.cursor_api = cursor_api  # neue Immich-Versionen (Cursor statt Seitenzahlen)
        self.rng = random.Random(seed)
        self.assets: dict[str, dict] = {}
        self.spec: dict[str, dict] = {}   # wie das Vorschaubild aussehen soll
        self.trash: set[str] = set()
        self.albums: dict[str, dict] = {}
        self.stacks: dict[str, list[str]] = {}
        self.dups: dict[str, list[str]] = {}
        self.tokens: set[str] = set()
        self.calls: list[tuple] = []
        self.build()

    # -----------------------------------------------------------------------
    def add(self, name, when: datetime, *, kind="IMAGE", scene=0, shift=0, blur=0, dark=False, flat=False, city=None,
            country=None, state=None, make=None, model=None, size=None, dur=None, fav=False, archived=False, w=4000, h=3000):
        aid = _uuid(self.rng)
        iso = when.astimezone(timezone.utc).isoformat().replace("+00:00", ".000Z")
        local = when.replace(tzinfo=None).isoformat() + ".000Z"
        self.assets[aid] = {
            "id": aid, "type": kind, "originalFileName": name, "originalPath": f"/data/library/till/{when:%Y}/{when:%Y-%m-%d}/{name}",
            "fileCreatedAt": iso, "localDateTime": local, "createdAt": iso, "fileModifiedAt": iso, "updatedAt": iso,
            "isFavorite": fav, "isArchived": archived, "visibility": "archive" if archived else "timeline",
            "isTrashed": False, "isOffline": False, "hasMetadata": True, "checksum": base64.b64encode(aid.encode()[:20]).decode(),
            "duration": dur, "livePhotoVideoId": None, "ownerId": USER_ID, "thumbhash": None, "width": w, "height": h,
            "duplicateId": None, "stack": None, "originalMimeType": "image/jpeg",
            "exifInfo": {"make": make, "model": model, "city": city, "state": state, "country": country,
                         "fileSizeInByte": size or self.rng.randint(2_000_000, 6_000_000), "exifImageWidth": w, "exifImageHeight": h,
                         "latitude": 1.0 if city else None, "longitude": 1.0 if city else None},
        }
        self.spec[aid] = {"scene": scene, "shift": shift, "blur": blur, "dark": dark, "flat": flat}
        return aid

    def build(self):
        tz = timezone(timedelta(hours=1))
        home = dict(city="Köln", state="Nordrhein-Westfalen", country="Germany", make="Google", model="Pixel 8")
        scene = 100
        # Alltag zu Hause: über ein Jahr verteilt
        start = datetime(2025, 1, 4, 12, 0, tzinfo=tz)
        for i in range(70):
            t = start + timedelta(days=i * 4, hours=self.rng.randint(-3, 6))
            scene += 1
            self.add(f"PXL_{t:%Y%m%d_%H%M%S}{i:03d}.jpg", t, scene=scene, **home)
        # Ein Geburtstag zu Hause (viele Fotos an einem Tag)
        t0 = datetime(2025, 6, 14, 15, 0, tzinfo=tz)
        for i in range(20):
            scene += 1
            self.add(f"PXL_20250614_{i:04d}.jpg", t0 + timedelta(minutes=i * 7), scene=scene, **home)
        # Bali-Reise: 6 Tage, Handy + Fujifilm X-S20 (ohne GPS)
        trip = datetime(2025, 3, 10, 9, 0, tzinfo=timezone(timedelta(hours=8)))
        for d in range(6):
            city = ["Denpasar", "Ubud", "Ubud", "Ubud", "Canggu", "Canggu"][d]
            for i in range(7):
                t = trip + timedelta(days=d, hours=i * 1.5)
                scene += 1
                self.add(f"PXL_{t:%Y%m%d_%H%M%S}.jpg", t, scene=scene, city=city, state="Bali", country="Indonesia", make="Google", model="Pixel 8")
            for i in range(3):  # Kamera: RAF + JPG
                t = trip + timedelta(days=d, hours=2 + i * 2, minutes=13)
                scene += 1
                n = 1000 + d * 10 + i
                self.add(f"DSCF{n}.JPG", t, scene=scene, make="FUJIFILM", model="X-S20", w=6240, h=4160)
                self.add(f"DSCF{n}.RAF", t, scene=scene, make="FUJIFILM", model="X-S20", size=55_000_000, w=6240, h=4160)
        # Eine Serie (5 Fotos in 3 Sekunden, fast gleich, eins unscharf)
        tb = datetime(2025, 3, 12, 17, 30, tzinfo=timezone(timedelta(hours=8)))
        scene += 1
        for i in range(5):
            self.add(f"PXL_20250312_1730{i:02d}.jpg", tb + timedelta(milliseconds=700 * i), scene=scene, shift=i * 3,
                     blur=6 if i == 2 else 0, city="Ubud", state="Bali", country="Indonesia", make="Google", model="Pixel 8")
        # Unscharfe und schwarze Bilder
        for i in range(4):
            scene += 1
            self.add(f"PXL_20250{5 + i}01_0800{i}.jpg", datetime(2025, 5 + i, 1, 8, 0, tzinfo=tz), scene=scene, blur=7, **home)
        for i in range(3):
            self.add(f"PXL_20250{7 + i}02_2200{i}.jpg", datetime(2025, 7 + i, 2, 22, 0, tzinfo=tz), dark=True, **home)
        self.add("PXL_20250805_120000.jpg", datetime(2025, 8, 5, 12, 0, tzinfo=tz), flat=True, **home)
        # Screenshots und Messenger
        for i in range(6):
            scene += 1
            self.add(f"Screenshot_2025{(i % 9) + 1:02d}10-1012{i:02d}_Chrome.png", datetime(2025, (i % 9) + 1, 10, 10, 12, tzinfo=tz),
                     scene=scene, w=1080, h=2400, size=400_000)
        for i in range(8):
            scene += 1
            self.add(f"IMG-2025{(i % 9) + 1:02d}0{(i % 8) + 1}-WA{i:04d}.jpg", datetime(2025, (i % 9) + 1, (i % 8) + 1, 19, 0, tzinfo=tz),
                     scene=scene, w=1200, h=1600, size=180_000)
        scene += 1
        self.add("photo_2025-04-02_18-22-11.jpg", datetime(2025, 4, 2, 18, 22, tzinfo=tz), scene=scene, w=1280, h=960, size=150_000)
        # Videos: zwei sehr kurze, ein großes
        self.add("PXL_20250420_101010.mp4", datetime(2025, 4, 20, 10, 10, tzinfo=tz), kind="VIDEO", scene=7, dur="0:00:01.200000",
                 size=3_000_000, **home)
        self.add("PXL_20250921_090000.mp4", datetime(2025, 9, 21, 9, 0, tzinfo=tz), kind="VIDEO", scene=8, dur=900, size=2_000_000, **home)
        self.add("PXL_20250313_190000.mp4", datetime(2025, 3, 13, 19, 0, tzinfo=timezone(timedelta(hours=8))), kind="VIDEO", scene=9,
                 dur="0:04:12.000000", size=950_000_000, city="Ubud", state="Bali", country="Indonesia", make="Google", model="Pixel 8")
        # Favorit (wird nie vorgeschlagen, auch wenn unscharf)
        scene += 1
        self.add("PXL_20251010_101010.jpg", datetime(2025, 10, 10, 10, 10, tzinfo=tz), scene=scene, blur=7, fav=True, **home)
        # Duplikate: dasselbe Bild zweimal (einmal verkleinert)
        scene += 1
        a = self.add("PXL_20250701_120000.jpg", datetime(2025, 7, 1, 12, 0, tzinfo=tz), scene=scene, **home)
        b = self.add("PXL_20250701_120000(1).jpg", datetime(2025, 7, 1, 12, 0, 1, tzinfo=tz), scene=scene, size=300_000, w=1600, h=1200, **home)
        did = _uuid(self.rng)
        self.dups[did] = [a, b]
        self.assets[a]["duplicateId"] = self.assets[b]["duplicateId"] = did
        # Archiviert
        scene += 1
        self.add("PXL_20250202_020202.jpg", datetime(2025, 2, 2, 2, 2, tzinfo=tz), scene=scene, archived=True, blur=7, **home)
        # Ein Album mit den ersten zehn Alltagsfotos
        alb = _uuid(self.rng)
        self.albums[alb] = {"id": alb, "albumName": "Alltag", "assetIds": list(self.assets)[:10]}

    # -----------------------------------------------------------------------
    def visible(self, a: dict) -> bool:
        return a["id"] not in self.trash

    def in_album(self, aid: str) -> bool:
        return any(aid in al["assetIds"] for al in self.albums.values())

    def render(self, aid: str, size: str) -> bytes:
        sp = self.spec[aid]
        W = 1440 if size == "preview" else 250
        H = int(W * 0.75)
        bases = sorted(glob.glob(os.environ.get("FAKE_PHOTOS", "/nonexistent") + "/*"))
        if sp["dark"]:
            img = Image.new("RGB", (W, H), (6, 6, 8))
            d = ImageDraw.Draw(img)
            d.ellipse((W * .45, H * .4, W * .5, H * .46), fill=(30, 26, 20))
        elif sp["flat"]:
            img = Image.new("RGB", (W, H), (182, 176, 168))
        elif bases:
            base = Image.open(bases[sp["scene"] % len(bases)]).convert("RGB")
            r = random.Random(sp["scene"])
            bw, bh = base.size
            cw, ch = int(bw * .8), int(bw * .8 * .75)
            ch = min(ch, bh)
            cw = int(ch / .75)
            x0 = r.randint(0, max(0, bw - cw)) + sp["shift"]
            y0 = r.randint(0, max(0, bh - ch))
            img = base.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H))
            if r.random() < .5:
                img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        else:
            r = random.Random(sp["scene"])
            img = Image.new("RGB", (W, H), tuple(r.randint(40, 200) for _ in range(3)))
            d = ImageDraw.Draw(img)
            for _ in range(60):
                x, y = r.randint(-50, W), r.randint(-50, H)
                s = r.randint(10, W // 4)
                col = tuple(r.randint(0, 255) for _ in range(3))
                x += sp["shift"] * W // 250
                (d.rectangle if r.random() < .5 else d.ellipse)((x, y, x + s, y + s * r.uniform(.4, 1.4)), fill=col, outline=(0, 0, 0))
            for _ in range(25):
                d.line((r.randint(0, W), r.randint(0, H), r.randint(0, W), r.randint(0, H)), fill=(255, 255, 255), width=2)
        if sp["blur"]:
            img = img.filter(ImageFilter.GaussianBlur(sp["blur"] * W / 1440 * 2))
        buf = io.BytesIO()
        img.save(buf, "JPEG" if size == "preview" else "WEBP", quality=82)
        return buf.getvalue()


LIB = Lib(cursor_api=os.environ.get("FAKE_CURSOR") == "1")


def auth(request: Request) -> bool:
    h = request.headers.get("authorization", "")
    return request.headers.get("x-api-key") == API_KEY or (h.startswith("Bearer ") and h[7:] in LIB.tokens)


def need(request: Request):
    if not auth(request):
        return JSONResponse({"message": "Authentication required", "statusCode": 401}, status_code=401)
    return None


async def ping(request):
    return JSONResponse({"res": "pong"})


async def version(request):
    return JSONResponse({"major": 3 if LIB.cursor_api else 2, "minor": 4 if LIB.cursor_api else 3, "patch": 0, "prerelease": None, "featureLevel": 1})


async def login(request):
    data = await request.json()
    if data.get("email") != EMAIL or data.get("password") != PASSWORD:
        return JSONResponse({"message": "Incorrect email or password", "statusCode": 401}, status_code=401)
    tok = uuid.uuid4().hex
    LIB.tokens.add(tok)
    return JSONResponse({"accessToken": tok, "userId": USER_ID, "userEmail": EMAIL, "name": "Till", "isAdmin": True,
                         "profileImagePath": "", "shouldChangePassword": False, "isOnboarded": True})


async def logout(request):
    h = request.headers.get("authorization", "")
    LIB.tokens.discard(h[7:])
    return JSONResponse({"successful": True, "redirectUri": "/auth/login"})


async def me(request):
    if (r := need(request)):
        return r
    return JSONResponse({"id": USER_ID, "email": EMAIL, "name": "Till", "isAdmin": True})


async def stats(request):
    if (r := need(request)):
        return r
    vis = [a for a in LIB.assets.values() if LIB.visible(a)]
    return JSONResponse({"images": sum(a["type"] == "IMAGE" for a in vis), "videos": sum(a["type"] == "VIDEO" for a in vis), "total": len(vis)})


async def search(request):
    if (r := need(request)):
        return r
    b = await request.json()
    LIB.calls.append(("search", b))
    if LIB.cursor_api and "isArchived" in b:
        return JSONResponse({"message": ["property isArchived should not exist"], "statusCode": 400}, status_code=400)
    items = [a for a in LIB.assets.values() if LIB.visible(a)]
    if "visibility" in b:
        items = [a for a in items if a["visibility"] == b["visibility"]]
    elif "isArchived" in b:
        items = [a for a in items if a["isArchived"] == b["isArchived"]]
    if b.get("isNotInAlbum"):
        items = [a for a in items if not LIB.in_album(a["id"])]
    items.sort(key=lambda a: a["fileCreatedAt"], reverse=True)
    size = int(b.get("size") or 250)
    if LIB.cursor_api:
        start = int(b.get("cursor") or 0)
    else:
        start = (int(b.get("page") or 1) - 1) * size
    chunk = items[start:start + size]
    out = []
    for a in chunk:
        x = copy.deepcopy(a)
        if not b.get("withExif"):
            x.pop("exifInfo", None)
        if LIB.cursor_api:
            x["duration"] = _ms(x["duration"])
        sid = next((k for k, v in LIB.stacks.items() if a["id"] in v), None)
        x["stack"] = {"id": sid, "primaryAssetId": LIB.stacks[sid][0], "assetCount": len(LIB.stacks[sid])} if sid else None
        out.append(x)
    more = start + size < len(items)
    res = {"total": len(items), "count": len(out), "items": out, "facets": []}
    if LIB.cursor_api:
        res.update(nextCursor=str(start + size) if more else None, nextPage=None)
    else:
        res.update(nextPage=str(int(b.get("page") or 1) + 1) if more else None)
    return JSONResponse({"albums": {"total": 0, "count": 0, "items": [], "facets": []}, "assets": res})


def _ms(v):
    if v is None or isinstance(v, int):
        return v
    h, m, s = v.split(":")
    return int((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)


async def duplicates(request):
    if (r := need(request)):
        return r
    out = []
    for did, ids in LIB.dups.items():
        members = [LIB.assets[i] for i in ids if LIB.visible(LIB.assets[i]) and LIB.assets[i]["duplicateId"] == did]
        if len(members) >= 2:
            out.append({"duplicateId": did, "assets": members, "suggestedKeepAssetIds": [members[0]["id"]]})
    return JSONResponse(out)


async def thumbnail(request):
    if (r := need(request)):
        return r
    aid = request.path_params["id"]
    if aid not in LIB.assets:
        return JSONResponse({"message": "Not found"}, status_code=404)
    size = request.query_params.get("size", "thumbnail")
    return Response(LIB.render(aid, size), media_type="image/jpeg" if size == "preview" else "image/webp")


async def playback(request):
    if (r := need(request)):
        return r
    data = b"\x00" * 200_000
    rng = request.headers.get("range")
    if rng and rng.startswith("bytes="):
        a, _, b = rng[6:].partition("-")
        a = int(a or 0)
        b = int(b) if b else len(data) - 1
        return Response(data[a:b + 1], status_code=206, media_type="video/mp4",
                        headers={"Content-Range": f"bytes {a}-{b}/{len(data)}", "Accept-Ranges": "bytes"})
    return Response(data, media_type="video/mp4", headers={"Accept-Ranges": "bytes"})


async def assets_delete(request):
    if (r := need(request)):
        return r
    b = await request.json()
    LIB.calls.append(("delete", b))
    LIB.trash.update(i for i in b["ids"] if i in LIB.assets)
    return Response(status_code=204)


async def assets_update(request):
    if (r := need(request)):
        return r
    b = await request.json()
    LIB.calls.append(("update", b))
    for i in b["ids"]:
        if i in LIB.assets:
            if "isFavorite" in b:
                LIB.assets[i]["isFavorite"] = b["isFavorite"]
            if "duplicateId" in b:
                LIB.assets[i]["duplicateId"] = b["duplicateId"]
    return Response(status_code=204)


async def restore(request):
    if (r := need(request)):
        return r
    b = await request.json()
    n = sum(1 for i in b["ids"] if i in LIB.trash)
    LIB.trash.difference_update(b["ids"])
    return JSONResponse({"count": n})


async def empty(request):
    if (r := need(request)):
        return r
    n = len(LIB.trash)
    for i in list(LIB.trash):
        LIB.assets.pop(i, None)
    LIB.trash.clear()
    return JSONResponse({"count": n})


async def albums(request):
    if (r := need(request)):
        return r
    if request.method == "POST":
        b = await request.json()
        aid = str(uuid.uuid4())
        LIB.albums[aid] = {"id": aid, "albumName": b["albumName"], "assetIds": list(b.get("assetIds") or [])}
        LIB.calls.append(("album", b))
        return JSONResponse(_album(LIB.albums[aid]), status_code=201)
    return JSONResponse([_album(a) for a in LIB.albums.values()])


def _album(a):
    return {"id": a["id"], "albumName": a["albumName"], "assetCount": len(a["assetIds"]),
            "albumThumbnailAssetId": a["assetIds"][0] if a["assetIds"] else None, "shared": False}


async def album_assets(request):
    if (r := need(request)):
        return r
    al = LIB.albums.get(request.path_params["id"])
    if not al:
        return JSONResponse({"message": "Not found"}, status_code=404)
    b = await request.json()
    res = []
    for i in b["ids"]:
        if i in al["assetIds"]:
            res.append({"id": i, "success": False, "error": "duplicate"})
        else:
            al["assetIds"].append(i)
            res.append({"id": i, "success": True})
    return JSONResponse(res)


async def stacks(request):
    if (r := need(request)):
        return r
    b = await request.json()
    sid = str(uuid.uuid4())
    LIB.stacks[sid] = b["assetIds"]
    return JSONResponse({"id": sid, "primaryAssetId": b["assetIds"][0], "assets": []}, status_code=201)


app = Starlette(routes=[
    Route("/api/server/ping", ping),
    Route("/api/server/version", version),
    Route("/api/auth/login", login, methods=["POST"]),
    Route("/api/auth/logout", logout, methods=["POST"]),
    Route("/api/users/me", me),
    Route("/api/assets/statistics", stats),
    Route("/api/search/metadata", search, methods=["POST"]),
    Route("/api/duplicates", duplicates),
    Route("/api/assets/{id}/thumbnail", thumbnail),
    Route("/api/assets/{id}/video/playback", playback),
    Route("/api/assets/{id}/original", playback),
    Route("/api/assets", assets_delete, methods=["DELETE"]),
    Route("/api/assets", assets_update, methods=["PUT"]),
    Route("/api/trash/restore/assets", restore, methods=["POST"]),
    Route("/api/trash/empty", empty, methods=["POST"]),
    Route("/api/albums", albums, methods=["GET", "POST"]),
    Route("/api/albums/{id}/assets", album_assets, methods=["PUT"]),
    Route("/api/stacks", stacks, methods=["POST"]),
])

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "2283")), log_level="warning")
