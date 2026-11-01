"""Every supervisor rule has a failing scenario."""

import pytest

from drone.driver import Telemetry
from drone.safety import Command, SafetySupervisor, point_in_polygon
from drone.site import load_site

NOW = 100.0


@pytest.fixture
def sup() -> SafetySupervisor:
    return SafetySupervisor(load_site()["drone"])


def tel(**kw) -> Telemetry:
    base = {"ts": NOW, "x": 5.0, "y": 5.0, "z": 1.5, "yaw_deg": 90.0, "battery_pct": 90.0, "has_fix": True,
            "fix_source": "sim", "airborne": True, "last_fix_ts": NOW}
    return Telemetry(**{**base, **kw})


def test_nominal_command_passes(sup):
    r = sup.check(Command(0.3, 0.2, 0.0, 10), tel(), NOW)
    assert r.action == "ok" and r.command.vx == 0.3


def test_stop_flag_lands_and_latches(sup):
    r = sup.check(Command(0.5, 0, 0, 0), tel(), NOW, stop_requested=True)
    assert r.action == "land" and "STOP" in r.reasons[0] and r.command.vx == 0
    assert sup.check(Command(0.5, 0, 0, 0), tel(), NOW).action == "land"  # latched


def test_low_battery_lands(sup):
    assert sup.check(Command(), tel(battery_pct=29.0), NOW).action == "land"


def test_battery_at_threshold_ok(sup):
    assert sup.check(Command(), tel(battery_pct=30.0), NOW).action == "ok"


def test_lost_fix_over_limit_lands(sup):
    r = sup.check(Command(), tel(has_fix=False, last_fix_ts=NOW - 2.5), NOW)
    assert r.action == "land" and "fix" in r.reasons[0]


def test_short_fix_dropout_tolerated(sup):
    assert sup.check(Command(), tel(has_fix=False, last_fix_ts=NOW - 1.0), NOW).action == "ok"


def test_lost_link_lands(sup):
    assert sup.check(Command(), tel(), NOW, link_down_s=6.0).action == "land"


def test_person_too_close_holds(sup):
    r = sup.check(Command(0.5, 0, 0, 0), tel(), NOW, people_xy=[(6.5, 5.5)])
    assert r.action == "hold" and r.command.vx == 0 and r.command.vy == 0


def test_person_far_away_ok(sup):
    assert sup.check(Command(0.5, 0, 0, 0), tel(), NOW, people_xy=[(9.0, 5.0)]).action == "ok"


def test_speed_clamped(sup):
    r = sup.check(Command(3.0, 4.0, 2.0, 400), tel(), NOW)
    assert r.action == "clamp"
    assert (r.command.vx ** 2 + r.command.vy ** 2) ** 0.5 == pytest.approx(1.0)
    assert r.command.vz == pytest.approx(1.0) and r.command.yaw_rate == 90


def test_geofence_lookahead_blocks_exit(sup):
    r = sup.check(Command(0, 1.0, 0, 0), tel(y=7.7), NOW)  # fence edge at y=7.8
    assert r.action == "clamp" and r.command.vy == 0


def test_outside_geofence_lands(sup):
    assert sup.check(Command(), tel(y=8.5), NOW).action == "land"


def test_max_alt_blocks_climb(sup):
    r = sup.check(Command(0, 0, 0.8, 0), tel(z=3.9), NOW)
    assert r.action == "clamp" and r.command.vz == 0


def test_over_max_alt_lands(sup):
    assert sup.check(Command(), tel(z=4.8), NOW).action == "land"


def test_mission_validation(sup):
    site = load_site()
    assert sup.validate_mission(["bay-B-01", "bay-B-04"], site) == (True, None)
    assert sup.validate_mission(["bay-Z-99"], site)[0] is False
    assert sup.validate_mission([], site)[0] is False


def test_advisory_action_validation(sup):
    assert sup.validate_action("next_bay", tel()) == ("next_bay", None)
    assert sup.validate_action("next_bay", tel(battery_pct=35))[0] == "return_home"
    assert sup.validate_action("move_closer", tel(), closer_target=(5, 9.0, 1.5))[0] == "rescan"
    assert sup.validate_action("rescan", tel(), rescans_left=0)[0] == "next_bay"
    assert sup.validate_action("fly_to_the_moon", tel())[0] == "return_home"


def test_point_in_polygon():
    sq = [[0, 0], [1, 0], [1, 1], [0, 1]]
    assert point_in_polygon(0.5, 0.5, sq) and not point_in_polygon(1.5, 0.5, sq)
