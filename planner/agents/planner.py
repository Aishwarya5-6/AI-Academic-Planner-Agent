"""Planner agent: allocates the remaining study hours of every topic onto calendar
days, respecting daily availability and exam deadlines.

Each day's capacity is filled block by block. A block goes to the subject with
the highest urgency score, i.e. hours still needed per day left before its exam,
boosted for weak subjects and damped for subjects already studied that day so
days stay varied. The final revision topic only becomes eligible in the last
few days before its exam."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

EPS = 0.01
MIN_BLOCK = 0.25
EXAM_DAY_CAPACITY = 0.5  # fraction of normal capacity left on a day you sit another exam


def weakness_factor(weakness: int) -> float:
    """Weak subjects get more hours than the raw estimate (weakness 5 => 1.6x)."""
    return 1.0 + 0.15 * (weakness - 1)


def round_quarter(h: float) -> float:
    return round(h * 4) / 4


@dataclass
class PlanResult:
    sessions: list[tuple[date, int, float]] = field(default_factory=list)  # (day, topic_id, hours)
    shortfall: dict[int, float] = field(default_factory=dict)  # subject_id -> unscheduled hours
    required_hours: dict[int, float] = field(default_factory=dict)  # subject_id -> remaining hours
    capacity_hours: float = 0.0


def topic_targets(subjects: list[dict], topics: list[dict], done: dict[int, float]) -> dict[int, float]:
    """Remaining hours per topic = estimate x weakness factor - hours already studied."""
    weak = {s["id"]: s["weakness"] for s in subjects}
    out = {}
    for t in topics:
        if t["completed"] or t["subject_id"] not in weak:
            continue
        target = t["est_hours"] * weakness_factor(weak[t["subject_id"]])
        rem = round_quarter(target - done.get(t["id"], 0.0))
        if rem >= MIN_BLOCK:
            out[t["id"]] = rem
    return out


def build_schedule(subjects: list[dict], topics: list[dict], done: dict[int, float],
                   weekday_hours: dict[str, float], session_length: float, start: date,
                   used_today: float = 0.0) -> PlanResult:
    result = PlanResult()
    remaining = topic_targets(subjects, topics, done)
    exam = {s["id"]: date.fromisoformat(s["exam_date"]) for s in subjects}
    weak = {s["id"]: s["weakness"] for s in subjects}
    exam_days = set(exam.values())

    # Per-subject ordered queues: [topic_id, hours_left, is_revision]
    queues: dict[int, list[list]] = defaultdict(list)
    for t in sorted(topics, key=lambda t: (t["subject_id"], t["is_revision"], t["position"])):
        if t["id"] in remaining:
            queues[t["subject_id"]].append([t["id"], remaining[t["id"]], bool(t["is_revision"])])
    for sid, q in queues.items():
        result.required_hours[sid] = sum(item[1] for item in q)

    def subject_left(sid: int) -> float:
        return sum(item[1] for item in queues[sid])

    def eligible(sid: int, day: date) -> bool:
        q = queues[sid]
        if not q or exam[sid] <= day:
            return False
        head_topic, head_left, is_rev = q[0]
        if not is_rev:
            return True
        # Revision waits until close to the exam so it is fresh.
        days_left = (exam[sid] - day).days
        return days_left <= max(3, math.ceil(head_left / max(session_length, MIN_BLOCK)) + 1)

    last_exam = max(exam.values(), default=start)
    day_cap: dict[date, float] = {}
    d = start
    while d < last_exam:
        cap = float(weekday_hours.get(str(d.weekday()), 0.0))
        if d in exam_days:
            cap *= EXAM_DAY_CAPACITY
        if d == start:
            cap = max(0.0, cap - used_today)
        day_cap[d] = round_quarter(cap)
        d += timedelta(days=1)
    result.capacity_hours = sum(day_cap.values())

    def is_critical(sid: int, day: date, cap_today: float) -> bool:
        """Earliest-deadline check: would the work due by this exam no longer fit if we skipped it now?"""
        needed = sum(subject_left(o) for o in queues if exam[o] <= exam[sid])
        capacity = cap_today + sum(c for d, c in day_cap.items() if day < d < exam[sid])
        return needed >= capacity - session_length

    day = start
    alloc: dict[tuple[date, int], float] = defaultdict(float)
    while day < last_exam:
        cap = day_cap[day]
        blocks_today: dict[int, int] = defaultdict(int)

        while cap >= MIN_BLOCK:
            candidates = [sid for sid in queues if eligible(sid, day)]
            if not candidates:
                break

            def score(sid: int) -> float:
                days_left = (exam[sid] - day).days
                return (subject_left(sid) / days_left) * (1 + 0.1 * (weak[sid] - 1)) * (0.6 ** blocks_today[sid])

            critical = [s for s in candidates if is_critical(s, day, cap)]
            if critical:
                sid = min(critical, key=lambda s: exam[s])
            else:
                sid = max(candidates, key=lambda s: (score(s), -exam[s].toordinal()))
            block = min(session_length, cap)
            q = queues[sid]
            while block >= MIN_BLOCK and q:
                if q[0][2] and not eligible(sid, day):
                    break  # only revision left and it is not yet due
                h = min(block, q[0][1])
                alloc[(day, q[0][0])] += h
                q[0][1] = round_quarter(q[0][1] - h)
                block -= h
                cap -= h
                if q[0][1] < MIN_BLOCK:
                    q.pop(0)
            # If the subject ran dry mid-block, the leftover capacity goes to the next pick.
            blocks_today[sid] += 1
        day += timedelta(days=1)

    result.sessions = [(d, tid, h) for (d, tid), h in sorted(alloc.items()) if h >= MIN_BLOCK]
    result.shortfall = {sid: left for sid in queues if (left := subject_left(sid)) > EPS}
    return result
