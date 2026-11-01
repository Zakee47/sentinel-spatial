from __future__ import annotations

import pytest
from sentinel_decisions import _mock

from perception.reach import ReachCallbacks, ReachMachine


def _callbacks(holding_value: float = 0.9, outcome_value: str = "back_on_shelf") -> ReachCallbacks:
    return ReachCallbacks(
        shelf_crop=lambda _zone_id: b"x",
        before_crop=lambda _zone_id: b"x",
        hand_crop=lambda _track_id: b"x",
        holding_product=lambda _hand, _shelf: _mock("holding_product", holding_value),
        reach_outcome=lambda _before, _after, _hand: _mock("reach_outcome", outcome_value),
    )


def _reach_until_pickup(machine: ReachMachine, track_id: str = "shopper-1") -> list[dict]:
    events = []
    for frame in range(3):
        events.extend(machine.update(track_id, frame / 10, "shelf-2", "SKU-006", True))
    assert machine.tracks[track_id].state == "REACHING"
    for frame in range(3):
        events.extend(machine.update(track_id, 0.3 + frame / 10, None, None, True))
    return events


def test_reach_emits_pickup_then_put_back() -> None:
    machine = ReachMachine(_callbacks())

    events = _reach_until_pickup(machine)

    assert machine.tracks["shopper-1"].state == "CARRYING"
    assert len(events) == 1
    pickup = events[0]
    assert pickup["type"] == "pick_up"
    assert pickup["zone_id"] == "shelf-2"
    assert pickup["product_id"] == "SKU-006"
    assert pickup["confidence"] == pytest.approx(0.9)
    assert pickup["decision"]["answer"]["value"] == pytest.approx(0.9)
    outcome = machine.update("shopper-1", 0.6, None, None, False)
    assert len(outcome) == 1
    assert outcome[0]["type"] == "put_back"
    assert outcome[0]["payload"]["outcome"] == "back_on_shelf"
    assert machine.tracks["shopper-1"].state == "IDLE"


@pytest.mark.parametrize(
    ("outcome_value", "event_type"),
    [("back_on_shelf", "put_back"), ("in_basket", "kept")],
)
def test_reach_maps_outcome_decision_to_event(
    outcome_value: str,
    event_type: str,
) -> None:
    machine = ReachMachine(_callbacks(outcome_value=outcome_value))
    assert len(_reach_until_pickup(machine)) == 1

    events = machine.update("shopper-1", 0.6, None, None, False)

    assert len(events) == 1
    assert events[0]["type"] == event_type
    assert events[0]["payload"]["outcome"] == outcome_value


def test_low_holding_probability_discards_reach_and_returns_to_idle() -> None:
    machine = ReachMachine(_callbacks(holding_value=0.2))

    events = _reach_until_pickup(machine)

    assert events == []
    assert machine.tracks["shopper-1"].state == "IDLE"


def test_lost_track_while_carrying_emits_outcome() -> None:
    machine = ReachMachine(_callbacks())
    assert len(_reach_until_pickup(machine)) == 1

    events = machine.lost("shopper-1")

    assert len(events) == 1
    assert events[0]["type"] == "put_back"
    assert events[0]["product_id"] == "SKU-006"
    assert "shopper-1" not in machine.tracks


def test_outcome_timeout_fires_while_still_near_shelf() -> None:
    machine = ReachMachine(_callbacks(), outcome_after_s=1.0)
    assert len(_reach_until_pickup(machine)) == 1
    assert machine.update("shopper-1", 1.49, None, None, True) == []

    events = machine.update("shopper-1", 1.5, None, None, True)

    assert len(events) == 1
    assert events[0]["type"] == "put_back"
