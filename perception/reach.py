"""Wrist-in-shelf-zone reach state machine.

IDLE --wrist in zone for ≥ enter_frames--> REACHING (before-crop taken)
REACHING --wrist out of zone for ≥ exit_frames--> HOLD_CHECK: holding_product(hand, shelf)
   holding ≥ review threshold -> `pick_up`, state CARRYING; else back to IDLE
CARRYING --person leaves the shelf neighbourhood, track lost, or outcome_after_s elapses-->
   reach_outcome(before, after, hand) -> `put_back` (back_on_shelf) | `kept` (in_basket/still_holding)

Side effects (crops, decisions) are injected via callbacks so the logic is unit-testable.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReachContext:
    zone_id: str
    product_id: str | None
    start_t: float
    before: Any = None  # shelf crop (jpeg bytes) before the reach
    hand: Any = None
    pick_event: dict | None = None
    released_t: float | None = None


@dataclass
class _Track:
    state: str = "IDLE"
    in_count: int = 0
    out_count: int = 0
    ctx: ReachContext | None = None
    zone_id: str | None = None


@dataclass
class ReachCallbacks:
    shelf_crop: Callable[[str], Any]  # zone_id -> jpeg bytes (current frame)
    before_crop: Callable[[str], Any]  # zone_id -> jpeg bytes (frame buffered ~0.5 s ago)
    hand_crop: Callable[[str], Any]  # track_id -> jpeg bytes
    holding_product: Callable[[Any, Any], Any]  # -> Decision
    reach_outcome: Callable[[Any, Any, Any], Any]  # -> Decision
    holding_threshold: float = 0.55


@dataclass
class ReachMachine:
    cb: ReachCallbacks
    enter_frames: int = 2
    exit_frames: int = 3
    outcome_after_s: float = 3.0
    tracks: dict[str, _Track] = field(default_factory=dict)

    def update(self, track_id: str, t: float, wrist_zone: str | None, product_id: str | None, near_shelf: bool) -> list[dict]:
        tr = self.tracks.setdefault(track_id, _Track())
        out: list[dict] = []
        if tr.state == "IDLE":
            if wrist_zone is not None and (tr.zone_id in (None, wrist_zone)):
                tr.zone_id = wrist_zone
                tr.in_count += 1
                if tr.in_count >= self.enter_frames:
                    tr.state = "REACHING"
                    tr.ctx = ReachContext(wrist_zone, product_id, t, before=self.cb.before_crop(wrist_zone))
                    tr.out_count = 0
            else:
                tr.in_count, tr.zone_id = 0, None
        elif tr.state == "REACHING":
            assert tr.ctx
            if wrist_zone == tr.ctx.zone_id:
                tr.out_count = 0
                if product_id:
                    tr.ctx.product_id = product_id
            else:
                tr.out_count += 1
                if tr.out_count >= self.exit_frames:
                    out += self._hold_check(track_id, tr, t)
        elif tr.state == "CARRYING":
            assert tr.ctx and tr.ctx.released_t is not None
            if not near_shelf or t - tr.ctx.released_t >= self.outcome_after_s:
                out += self._outcome(track_id, tr)
        return out

    def lost(self, track_id: str) -> list[dict]:
        tr = self.tracks.pop(track_id, None)
        if tr and tr.state == "CARRYING":
            return self._outcome(track_id, tr)
        return []

    def flush(self) -> list[dict]:
        out: list[dict] = []
        for tid in list(self.tracks):
            out += self.lost(tid)
        return out

    def _hold_check(self, track_id: str, tr: _Track, t: float) -> list[dict]:
        ctx = tr.ctx
        assert ctx
        ctx.hand = self.cb.hand_crop(track_id)
        d = self.cb.holding_product(ctx.hand, self.cb.shelf_crop(ctx.zone_id))
        p = float(d.value) if isinstance(d.value, (int, float)) else 0.0
        if d.policy in ("ignore", "unclear") or p < self.cb.holding_threshold:
            self._reset(tr)
            return []
        ctx.released_t = t
        ev = {"type": "pick_up", "track_id": track_id, "zone_id": ctx.zone_id, "product_id": ctx.product_id,
              "confidence": d.confidence, "decision": d.to_event_decision(), "payload": {"reach_s": round(t - ctx.start_t, 2)}}
        ctx.pick_event = ev
        tr.state = "CARRYING"
        return [ev]

    def _outcome(self, track_id: str, tr: _Track) -> list[dict]:
        ctx = tr.ctx
        assert ctx
        d = self.cb.reach_outcome(ctx.before, self.cb.shelf_crop(ctx.zone_id), ctx.hand)
        self._reset(tr)
        kind = {"back_on_shelf": "put_back", "in_basket": "kept", "still_holding": "kept"}.get(str(d.value))
        if kind is None:
            return []
        return [{"type": kind, "track_id": track_id, "zone_id": ctx.zone_id, "product_id": ctx.product_id,
                 "confidence": d.confidence, "decision": d.to_event_decision(), "payload": {"outcome": d.value}}]

    @staticmethod
    def _reset(tr: _Track) -> None:
        tr.state, tr.in_count, tr.out_count, tr.ctx, tr.zone_id = "IDLE", 0, 0, None, None
