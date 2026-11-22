"""Bildanalyse auf Immichs Vorschaubildern: Schärfe, Helligkeit, Kontrast und ein Fingerabdruck für Ähnlichkeit.

- Schärfe: Varianz des Laplace-Filters – in 4×4 Kacheln, gewertet wird die zweitschärfste Kachel.
  So gilt ein Porträt mit unscharfem Hintergrund (Bokeh) trotzdem als scharf, solange das Motiv scharf ist.
- Helligkeit/Kontrast: Mittelwert, Streuung und hellste Stellen (98 %) der Graustufen – schwarze Bilder und
  Fehlauslösungen in der Tasche; Nachtfotos mit Lichtern haben helle Stellen und zählen nicht dazu.
- Fingerabdruck (dHash, 64 Bit): ähnliche Bilder unterscheiden sich in wenigen Bits → Serien erkennen.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps

try:  # HEIC-Vorschauen (falls Immich so eingestellt ist)
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
except Exception:  # noqa: BLE001
    pass

SIZE = 640
Image.MAX_IMAGE_PIXELS = 200_000_000


def analyze(data: bytes) -> dict:
    img = Image.open(io.BytesIO(data))
    try:
        img.draft("L", (SIZE * 2, SIZE * 2))  # JPEG: schon beim Dekodieren verkleinern (schnell)
    except Exception:  # noqa: BLE001
        pass
    img = ImageOps.exif_transpose(img) if hasattr(img, "getexif") else img
    g = img.convert("L")
    g.thumbnail((SIZE, SIZE), Image.Resampling.BILINEAR)
    a = np.asarray(g, dtype=np.float32)
    return analyze_array(a, g)


def analyze_array(a: np.ndarray, g: Image.Image | None = None) -> dict:
    h, w = a.shape
    if h < 8 or w < 8:
        return {"sharp": 0.0, "sharp_g": 0.0, "bright": float(a.mean()), "contrast": float(a.std()), "hi": float(a.max()), "dhash": 0}
    lap = (a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:] - 4 * a[1:-1, 1:-1])
    sharp_g = float(lap.var())
    tiles = []
    th, tw = lap.shape[0] // 4, lap.shape[1] // 4
    if th >= 4 and tw >= 4:
        for i in range(4):
            for j in range(4):
                t = lap[i * th:(i + 1) * th, j * tw:(j + 1) * tw]
                tiles.append(float(t.var()))
        tiles.sort(reverse=True)
        sharp = tiles[1]
    else:
        sharp = sharp_g
    if g is None:
        g = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return {"sharp": round(sharp, 2), "sharp_g": round(sharp_g, 2), "bright": round(float(a.mean()), 2),
            "contrast": round(float(a.std()), 2), "hi": round(float(np.percentile(a, 98)), 2), "dhash": dhash(g)}


def dhash(g: Image.Image) -> int:
    small = np.asarray(g.resize((9, 8), Image.Resampling.BILINEAR), dtype=np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    # SQLite speichert nur vorzeichenbehaftete 64-Bit-Zahlen
    return v - (1 << 64) if v >= (1 << 63) else v


def hamming(a: int | None, b: int | None) -> int:
    if a is None or b is None:
        return 64
    return bin((a ^ b) & ((1 << 64) - 1)).count("1")
