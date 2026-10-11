"""Schedule Optimizer agent: rebuilds the remaining schedule whenever reality
diverges from the plan (missed sessions, changed availability, new subjects),
and checks whether the plan is still feasible before each exam."""
from __future__ import annotations

from datetime import date

from planner.agents.planner import PlanResult, build_schedule
from planner.agents.progress_tracker import ProgressTracker
from planner.db import Database


class ScheduleOptimizer:
    name = "Schedule Optimizer"

    def __init__(self, db: Database, tracker: ProgressTracker):
        self.db = db
        self.tracker = tracker

    def replan(self, today: date, reason: str) -> PlanResult:
        settings = self.db.get_settings()
        subjects = [s for s in self.db.subjects() if date.fromisoformat(s["exam_date"]) > today]
        topics = self.db.topics()
        before = {(s["date"], s["topic_id"]) for s in self.db.sessions(today, status="planned")}

        result = build_schedule(
            subjects=subjects,
            topics=topics,
            done=self.db.done_hours_by_topic(),
            weekday_hours=settings["weekday_hours"],
            session_length=float(settings["session_length"]),
            start=today,
            used_today=self.tracker.hours_used_on(today),
        )
        self.db.replace_planned_sessions(today, result.sessions)

        after = {(d.isoformat(), tid) for d, tid, _ in result.sessions}
        moved = len(after - before)
        names = {s["id"]: s["name"] for s in subjects}
        msg = (f"Replanned ({reason}): {len(result.sessions)} sessions, "
               f"{sum(h for *_, h in result.sessions):g}h across {len(subjects)} subject(s); "
               f"{moved} slot(s) changed.")
        if result.shortfall:
            msg += " Not enough time for: " + ", ".join(
                f"{names[sid]} (short {h:g}h)" for sid, h in result.shortfall.items())
        self.db.log(self.name, msg)
        return result

    def feasibility(self, today: date) -> dict[int, float]:
        """Dry-run the planner and return subject_id -> hours that cannot fit."""
        settings = self.db.get_settings()
        subjects = [s for s in self.db.subjects() if date.fromisoformat(s["exam_date"]) > today]
        return build_schedule(subjects, self.db.topics(), self.db.done_hours_by_topic(),
                              settings["weekday_hours"], float(settings["session_length"]), today,
                              self.tracker.hours_used_on(today)).shortfall
