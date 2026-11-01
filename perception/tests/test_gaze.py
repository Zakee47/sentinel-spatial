from __future__ import annotations

import numpy as np
import pytest

from perception.gaze import (
    LookTracker,
    PassByTracker,
    cast_gaze,
    head_yaw_from_keypoints,
)
from perception.site import load_site


def _sample_zone(
    tracker: LookTracker,
    track_id: str,
    zone_id: str,
    start: float,
    stop: float,
    hit_xyz: np.ndarray | None = None,
) -> list[dict]:
    events = []
    steps = round((stop - start) * 10)
    for step in range(steps + 1):
        t = start + step / 10
        events.extend(tracker.update(track_id, t, zone_id, hit_xyz))
    return events


def test_two_second_dwell_closes_after_gaze_leaves_with_mean_hit() -> None:
    tracker = LookTracker(1.5, 5.0)
    hit = np.array([1.2, 2.3, 1.4])
    events = _sample_zone(tracker, "shopper-1", "A", 0.0, 1.9, hit)
    events.extend(tracker.update("shopper-1", 2.0, None))
    events.extend(tracker.expire(2.51))

    looks = [event for event in events if event["type"] == "look"]
    assert len(looks) == 1
    assert 1.9 <= looks[0]["payload"]["duration_s"] <= 2.0
    assert looks[0]["payload"]["gaze_hit_xyz"] == pytest.approx(hit.tolist())


def test_one_second_dwell_does_not_emit_look() -> None:
    tracker = LookTracker(1.5, 5.0)
    events = _sample_zone(tracker, "shopper-1", "A", 0.0, 0.9)
    events.extend(tracker.update("shopper-1", 1.0, None))
    events.extend(tracker.expire(1.51))
    assert events == []


def test_long_dwell_emits_interest_once_then_look_on_zone_switch() -> None:
    tracker = LookTracker(1.5, 5.0)
    events = _sample_zone(tracker, "shopper-1", "A", 0.0, 6.0, np.array([2.0, 2.2, 1.5]))

    events.extend(tracker.update("shopper-1", 6.1, "B"))

    interests = [event for event in events if event["type"] == "interest"]
    looks = [event for event in events if event["type"] == "look"]
    assert len(interests) == 1
    assert interests[0]["zone_id"] == "A"
    assert len(looks) == 1
    assert looks[0]["zone_id"] == "A"
    assert looks[0]["payload"]["duration_s"] == pytest.approx(6.0)


def test_short_none_gap_does_not_split_dwell() -> None:
    tracker = LookTracker(1.5, 5.0)
    _sample_zone(tracker, "shopper-1", "A", 0.0, 0.9)
    assert tracker.update("shopper-1", 1.0, None) == []
    assert tracker.update("shopper-1", 1.3, "A") == []
    _sample_zone(tracker, "shopper-1", "A", 1.4, 2.0)

    events = tracker.flush()

    assert len(events) == 1
    assert events[0]["type"] == "look"
    assert events[0]["payload"]["duration_s"] == pytest.approx(2.0)


def test_flush_closes_open_look() -> None:
    tracker = LookTracker(1.5, 5.0)
    _sample_zone(tracker, "shopper-1", "A", 0.0, 1.9)

    events = tracker.flush()

    assert len(events) == 1
    assert events[0]["type"] == "look"
    assert events[0]["zone_id"] == "A"


def test_pass_by_emits_once_when_track_enters_aisle() -> None:
    aisle = next(zone for zone in load_site().zones if zone.kind == "aisle_floor")
    tracker = PassByTracker(aisle)
    inside = np.array([2.5, 1.25])

    assert tracker.update("shopper-1", None) == []
    assert tracker.update("shopper-1", np.array([0.1, 1.0])) == []
    first = tracker.update("shopper-1", inside)
    assert len(first) == 1
    assert first[0]["type"] == "pass_by"
    assert first[0]["zone_id"] == "aisle-A-floor"
    assert tracker.update("shopper-1", inside) == []


def test_cast_gaze_hits_shelf_two_in_plus_y_direction_only() -> None:
    shelves = load_site().zones_of("retail_shelf")
    origin = np.array([2.0, 1.0, 1.6])

    toward_shelf = cast_gaze(origin, np.array([0.0, 1.0, 0.0]), shelves, 10.0)
    away = cast_gaze(origin, np.array([0.0, -1.0, 0.0]), shelves, 10.0)

    assert toward_shelf.zone_id == "aisle-A-shelf-2"
    assert toward_shelf.hit_xyz is not None
    assert away.zone_id is None
    assert away.hit_xyz is None


def test_head_yaw_is_zero_when_nose_is_between_ears() -> None:
    keypoints = np.zeros((17, 3), dtype=float)
    keypoints[[0, 1, 2, 3, 4], 2] = 0.9
    keypoints[0, 0] = 50.0
    keypoints[1, 0] = 45.0
    keypoints[2, 0] = 55.0
    keypoints[3, 0] = 40.0
    keypoints[4, 0] = 60.0

    yaw, facing_camera = head_yaw_from_keypoints(keypoints)

    assert yaw == pytest.approx(0.0)
    assert facing_camera is True


def test_head_yaw_with_only_ears_does_not_claim_facing_camera() -> None:
    keypoints = np.zeros((17, 3), dtype=float)
    keypoints[3] = [40.0, 20.0, 0.9]
    keypoints[4] = [60.0, 20.0, 0.9]

    yaw, facing_camera = head_yaw_from_keypoints(keypoints)

    assert yaw == pytest.approx(0.0)
    assert facing_camera is False
