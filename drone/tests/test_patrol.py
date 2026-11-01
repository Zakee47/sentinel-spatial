"""Full simulated patrols with a stepped clock (no server, mock decisions)."""

import time

import sentinel_decisions as sd

from drone.api import Link
from drone.decide import DecisionWorker
from drone.patrol import Patrol
from drone.safety import SafetySupervisor
from drone.sim import SimDriver
from drone.site import load_site

ALL = ["bay-B-01", "bay-B-02", "bay-B-03", "bay-B-04"]


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def make(bays=ALL, battery=100.0):
    site = load_site()
    clock = Clock()
    sim = SimDriver(site, clock=clock, battery_pct=battery)
    link = Link(None)  # offline: outbox is inspected directly
    link.inject_mission({"mission_id": "m-1", "bays": bays})
    p = Patrol(sim, SafetySupervisor(site["drone"]), site, link, DecisionWorker())
    return p, sim, clock, link


def run(p, sim, clock, seconds=90.0, hz=20.0, until_idle=True, hook=None, real_sleep=0.0):
    started = False
    for _ in range(int(seconds * hz)):
        clock.t += 1 / hz
        sim.step(1 / hz)
        if hook:
            hook(clock.t)
        p.tick(clock.t)
        if real_sleep:
            time.sleep(real_sleep)
        elif p.state == "DECIDE":
            time.sleep(0.002)  # let the decision thread finish (it runs in real time)
        started = started or p.state != "IDLE"
        if until_idle and started and p.state == "IDLE":
            break


def drain(link):
    items = []
    while not link.outbox.empty():
        items.append(link.outbox.get())
    return items


def test_full_patrol_flags_empty_and_misplaced():
    p, sim, clock, link = make()
    states = []
    run(p, sim, clock, hook=lambda t: states.append(p.state))
    states.append(p.state)
    assert p.state == "IDLE" and not sim.airborne
    assert [v.issue for v in p.verdicts] == ["ok", "empty", "misplaced", "ok"]
    seq = [s for i, s in enumerate(states) if i == 0 or s != states[i - 1]]
    assert seq[:4] == ["IDLE", "TAKEOFF", "GOTO_BAY", "INSPECT"] and seq[-3:] == ["RETURN", "LAND", "IDLE"]
    items = drain(link)
    issues = [i["event"] for i in items if i["event"]["type"] == "bay_issue"]
    assert {(e["zone_id"], e["payload"]["issue"]) for e in issues} == {("bay-B-02", "empty"), ("bay-B-03", "misplaced")}
    tasks = [i["task"] for i in items if i["task"]]
    assert {(t["zone_id"], t["kind"]) for t in tasks} == {("bay-B-02", "restock"), ("bay-B-03", "move")}
    assert all(e["source"] == "drone-1" for e in (i["event"] for i in items))
    assert all(e["payload"].get("state") for e in (i["event"] for i in items) if e["type"] == "patrol")


def test_every_command_inside_limits():
    p, sim, clock, _ = make()
    run(p, sim, clock)
    site = load_site()
    for e in p.log:
        vx, vy, _, _ = e.cmd
        assert (vx ** 2 + vy ** 2) ** 0.5 <= site["drone"]["max_speed_mps"] + 1e-9
        assert e.z <= site["drone"]["max_alt_m"]


def test_decision_timeout_holds(monkeypatch):
    def slow(*a, **k):
        time.sleep(0.4)
        return sd.Decision("bay_issue", {"type": "x"}, "ok", 0.9, "auto", 0.4)

    monkeypatch.setattr(sd, "bay_issue", slow)
    p, sim, clock, link = make(bays=["bay-B-01"])
    seen = []
    # 0.4 s real decision vs 2 s timeout on a fast clock (0.25 s per real 5 ms) -> HOLD, then resumes
    run(p, sim, clock, hook=lambda t: seen.append(p.state), real_sleep=0.005, seconds=60, hz=4)
    assert "HOLD" in seen and p.state == "IDLE"
    holds = [i["event"] for i in drain(link) if i["event"]["payload"].get("state") == "HOLD"]
    assert holds and holds[0]["payload"]["reason"] == "decision_timeout"


def test_stop_request_lands_immediately():
    p, sim, clock, link = make()

    def hook(t):
        if p.state == "GOTO_BAY" and sim.x < 4.0 and not link.snapshot().stop_requested:
            link.request_stop()

    run(p, sim, clock, hook=hook, seconds=30)
    assert p.state == "IDLE" and not sim.airborne and p.verdicts == []
    assert p.log[-1].x < 4.2 and p.log[-1].x > 3.0  # landed where it was, did not continue


def test_low_battery_mid_patrol_lands():
    p, sim, clock, _ = make(battery=31.0)
    run(p, sim, clock, seconds=60)
    assert p.state == "IDLE" and not sim.airborne and len(p.verdicts) < 4
    assert any("battery" in r for e in p.log for r in e.reasons)


def test_person_near_route_holds_then_resumes():
    p, sim, clock, link = make(bays=["bay-B-02"])
    seen = []

    def hook(t):
        seen.append(p.state)
        if p.state == "GOTO_BAY" and "HOLD" not in seen:
            link.set_people([(sim.x + 1.0, sim.y)])
        elif "HOLD" in seen and len([s for s in seen if s == "HOLD"]) > 20:
            link.set_people([])

    run(p, sim, clock, hook=hook)
    assert "HOLD" in seen and [v.bay_id for v in p.verdicts] == ["bay-B-02"] and p.state == "IDLE"


def test_invalid_mission_rejected():
    p, sim, clock, link = make(bays=["bay-Z-99"])
    run(p, sim, clock, seconds=2, until_idle=False)
    assert p.state == "IDLE" and not sim.airborne
    assert any(i["event"]["payload"].get("rejected_reason") for i in drain(link))
