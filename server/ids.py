"""Tiny ULID generator (Crockford base32, 48-bit ms timestamp + 80 random bits)."""

from __future__ import annotations

import os
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid(ts: float | None = None) -> str:
    ms = int((time.time() if ts is None else ts) * 1000)
    value = (ms << 80) | int.from_bytes(os.urandom(10), "big")
    out = []
    for _ in range(26):
        out.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(out))
