"""Mocked product catalogue (20 UK grocery SKUs) and hourly till sales for today.

SKU-007 (Lindt Excellence 70%) is the planted "high attention, low conversion" product:
the simulator makes shoppers look at it a lot, but it barely sells.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from .config import load_site

_CATALOGUE: list[tuple[str, str, str, float]] = [
    # (name, brand, barcode, price_gbp)
    ("Semi-Skimmed Milk 2 Pints", "Cravendale", "5000295142619", 1.85),
    ("Free Range Eggs 6 Pack", "Happy Egg Co", "5060196780065", 2.10),
    ("Salted Butter 250g", "Lurpak", "5740900400153", 3.25),
    ("Mature Cheddar 400g", "Cathedral City", "5000295038172", 4.50),
    ("Greek Style Yogurt 500g", "Yeo Valley", "5036589200496", 2.00),
    ("Medium Sliced White Bread 800g", "Warburtons", "5010044000701", 1.45),
    ("Excellence 70% Cocoa 100g", "Lindt", "3046920022606", 2.75),
    ("Dairy Milk 180g", "Cadbury", "7622210449283", 2.25),
    ("Digestive Biscuits 400g", "McVitie's", "5000168001272", 1.69),
    ("Ready Salted Crisps 6 Pack", "Walkers", "5000328657455", 2.00),
    ("Baked Beans 415g", "Heinz", "5000157024671", 1.40),
    ("Cream of Tomato Soup 400g", "Heinz", "5000157024688", 1.50),
    ("Tuna Chunks in Spring Water 145g", "John West", "5000171003256", 1.95),
    ("Penne Pasta 500g", "Napolina", "5014061003020", 1.25),
    ("Basmati Rice 1kg", "Tilda", "5011157633101", 3.20),
    ("Yorkshire Tea 80 Bags", "Taylors", "5010357000015", 3.50),
    ("Gold Instant Coffee 100g", "Nescafe", "7613036931028", 5.25),
    ("Orange Juice Smooth 1L", "Tropicana", "5017764110013", 2.60),
    ("Cola Zero 2L", "Coca-Cola", "5449000131836", 2.15),
    ("Sparkling Water 1L", "Highland Spring", "5010136000022", 0.95),
]

LOW_CONVERSION_SKU = "SKU-007"


def products() -> list[dict]:
    site = load_site()
    out = []
    for i, (name, brand, barcode, price) in enumerate(_CATALOGUE, start=1):
        pid = f"SKU-{i:03d}"
        out.append(
            {
                "product_id": pid,
                "name": name,
                "brand": brand,
                "barcode": barcode,
                "price_gbp": price,
                "zone_id": site.product_zone(pid) or "unassigned",
            }
        )
    return out


def sales_today(
    now: datetime | None = None, seed: int = 7
) -> list[tuple[datetime, str, int]]:
    """Hourly till units from 08:00 UTC today up to the current hour."""
    now = now or datetime.now(UTC)
    rng = random.Random(seed)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for h in range(8, max(now.hour, 8) + 1):
        ts_hour = day + timedelta(hours=h)
        for p in products():
            pid = p["product_id"]
            units = (
                rng.randint(0, 1) if pid == LOW_CONVERSION_SKU else rng.randint(4, 8)
            )
            rows.append((ts_hour, pid, units))
    return rows
