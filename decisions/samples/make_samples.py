"""Generate synthetic rack-bay photos for the demo and the sweep (python samples/make_samples.py)."""

from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent
W, H = 960, 720
LEVELS = [610, 420, 230]  # beam y (top of beam) for 3 levels
BAYS = [(80, 470), (490, 880)]  # x ranges of 2 pick-face columns


def carton(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, rng: random.Random, sku: str) -> None:
    base = (
        176 + rng.randint(-12, 12),
        132 + rng.randint(-10, 10),
        84 + rng.randint(-10, 10),
    )
    d.rectangle([x, y - h, x + w, y], fill=base, outline=(110, 80, 50), width=2)
    d.line([x, y - h + 10, x + w, y - h + 10], fill=(150, 110, 70), width=3)  # tape
    d.rectangle([x + 12, y - h + 28, x + 70, y - h + 52], fill=(245, 245, 240))
    d.text((x + 16, y - h + 33), sku, fill=(20, 20, 20))


def bay(kind: str, seed: int = 1) -> Image.Image:
    rng = random.Random(seed)
    img = Image.new("RGB", (W, H), (205, 205, 200))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 650, W, H], fill=(150, 150, 145))  # floor
    for x in (60, 475, 890):  # uprights
        d.rectangle([x, 60, x + 18, 650], fill=(40, 70, 150))
    for li, y in enumerate(LEVELS):
        d.rectangle([60, y, 908, y + 16], fill=(235, 120, 30))  # orange beam
        for bi, (x0, x1) in enumerate(BAYS):
            loc = f"B-01-{li + 1}{'AB'[bi]}"
            d.rectangle([x0 + 150, y + 2, x0 + 250, y + 14], fill=(255, 255, 255))
            d.text((x0 + 160, y + 3), loc, fill=(0, 0, 0))
            n = 4
            if kind == "empty" and (li, bi) == (1, 0):
                n = 0
            if kind == "low_stock" and (li, bi) in ((0, 1), (1, 1)):
                n = 1
            cw = (x1 - x0 - 20) // 4
            for k in range(n):
                carton(
                    d,
                    x0 + 6 + k * (cw + 4),
                    y,
                    cw - 4,
                    140 + rng.randint(-6, 6),
                    rng,
                    f"SKU-{100 + li * 10 + bi * 4 + k}",
                )
    if kind == "misplaced":
        carton(d, 520, 650, 160, 120, rng, "SKU-999")  # carton on the floor in front of the bay
        d.polygon(
            [(300, 420), (520, 420), (540, 290), (320, 290)],
            fill=(200, 150, 90),
            outline=(110, 80, 50),
        )
    return img.filter(ImageFilter.GaussianBlur(0.8))


if __name__ == "__main__":
    for kind in ("full", "empty", "low_stock", "misplaced"):
        bay(kind).save(OUT / f"bay_{kind}.jpg", quality=85)
        print("wrote", OUT / f"bay_{kind}.jpg")
