from collections import defaultdict
from datetime import date, timedelta

import pytest

from planner.agents.planner import build_schedule, topic_targets
from planner.agents.syllabus_analyzer import heuristic_topics
from planner.db import Database
from planner.orchestrator import Orchestrator
from planner.sample_data import load_sample

TODAY = date(2026, 10, 12)  # a Monday
HOURS = {str(i): 3.0 for i in range(7)}


def subj(sid, days, weakness=3):
    return {"id": sid, "name": f"S{sid}", "exam_date": (TODAY + timedelta(days=days)).isoformat(),
            "weakness": weakness}


def topic(tid, sid, hours, pos=0, rev=0):
    return {"id": tid, "subject_id": sid, "name": f"T{tid}", "est_hours": hours, "difficulty": 3,
            "position": pos, "is_revision": rev, "completed": 0}


def test_respects_capacity_and_deadlines():
    subjects = [subj(1, 5), subj(2, 10)]
    topics = [topic(1, 1, 4), topic(2, 1, 3, 1), topic(3, 2, 6), topic(4, 2, 2, 1, rev=1)]
    res = build_schedule(subjects, topics, {}, HOURS, 1.5, TODAY)
    per_day = defaultdict(float)
    for d, tid, h in res.sessions:
        per_day[d] += h
        sid = 1 if tid in (1, 2) else 2
        assert d < date.fromisoformat(subjects[sid - 1]["exam_date"])
    assert all(h <= 3.0 + 1e-9 for h in per_day.values())
    assert not res.shortfall
    # Every remaining hour is scheduled exactly once.
    assert sum(h for *_, h in res.sessions) == pytest.approx(sum(topic_targets(subjects, topics, {}).values()))


def test_reports_shortfall_when_infeasible():
    res = build_schedule([subj(1, 2)], [topic(1, 1, 20)], {}, HOURS, 1.5, TODAY)
    assert res.shortfall[1] > 0


def test_weak_subject_gets_more_hours():
    weak, strong = topic_targets([subj(1, 9, 5), subj(2, 9, 1)], [topic(1, 1, 4), topic(2, 2, 4)], {}).values()
    assert weak > strong


def test_revision_lands_near_exam():
    res = build_schedule([subj(1, 20)], [topic(1, 1, 3), topic(2, 1, 2, 1, rev=1)], {}, HOURS, 1.0, TODAY)
    rev_days = [d for d, tid, _ in res.sessions if tid == 2]
    assert rev_days and min(rev_days) >= TODAY + timedelta(days=16)


def test_heuristic_parser_strips_numbering():
    names = [t["name"] for t in heuristic_topics("1. Intro to sets\n- Graph theory\nUnit 3: Proof techniques")]
    assert names == ["Intro to sets", "Graph theory", "Proof techniques"]


def test_missed_session_is_redistributed():
    db = Database(":memory:")
    orch = Orchestrator(db)
    load_sample(orch, TODAY)
    first_day = db.sessions(TODAY, TODAY)
    assert first_day
    total_before = sum(s["hours"] for s in db.sessions(status="planned"))

    # Skip a day entirely: the tracker should flag it, and the optimizer reschedule it.
    missed = orch.run_cycle(TODAY + timedelta(days=1))
    assert len(missed) == len(first_day)
    assert all(s["status"] == "missed" for s in db.sessions(TODAY, TODAY))
    future = db.sessions(TODAY + timedelta(days=1), status="planned")
    assert sum(s["hours"] for s in future) == pytest.approx(total_before, abs=0.5)
    assert any("Replanned" in e["message"] for e in db.recent_log())


def test_completing_less_than_planned_triggers_replan():
    db = Database(":memory:")
    orch = Orchestrator(db)
    load_sample(orch, TODAY)
    s = db.sessions(TODAY, TODAY)[0]
    orch.complete_session(s, s["hours"] - 0.5, TODAY)
    assert db.done_hours_by_topic()[s["topic_id"]] == s["hours"] - 0.5
    # Today's remaining capacity accounts for what was already studied.
    today_planned = sum(x["hours"] for x in db.sessions(TODAY, TODAY, "planned"))
    assert today_planned + s["hours"] - 0.5 <= db.get_settings()["weekday_hours"]["0"] + 1e-9
