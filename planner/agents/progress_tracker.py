"""Progress Tracker agent: records what was studied, detects missed sessions and
reports how each subject is tracking against its plan."""
from __future__ import annotations

from datetime import date

from planner.agents.planner import weakness_factor
from planner.db import Database


class ProgressTracker:
    name = "Progress Tracker"

    def __init__(self, db: Database):
        self.db = db

    def sweep_overdue(self, today: date) -> list[dict]:
        """Any session still 'planned' on a past day was not done, so mark it missed."""
        overdue = [s for s in self.db.sessions(status="planned") if date.fromisoformat(s["date"]) < today]
        for s in overdue:
            self.db.set_session_status(s["id"], "missed")
        if overdue:
            hours = sum(s["hours"] for s in overdue)
            self.db.log(self.name, f"Detected {len(overdue)} missed session(s) ({hours:g}h) before "
                                   f"{today.isoformat()}: " + ", ".join(sorted({s['subject'] for s in overdue})))
        return overdue

    def complete(self, session: dict, actual_hours: float) -> None:
        self.db.set_session_status(session["id"], "done", actual_hours)
        self.db.log(self.name, f"Completed {actual_hours:g}h of '{session['topic']}' ({session['subject']}).")

    def miss(self, session: dict) -> None:
        self.db.set_session_status(session["id"], "missed")
        self.db.log(self.name, f"Session '{session['topic']}' ({session['subject']}) on {session['date']} "
                               f"marked as missed.")

    def hours_used_on(self, day: date) -> float:
        """Time already spent (or lost to missed sessions) on a day, so it isn't planned again."""
        return sum(s["actual_hours"] if s["status"] == "done" else s["hours"]
                   for s in self.db.sessions(day, day) if s["status"] != "planned")

    def subject_stats(self, today: date) -> list[dict]:
        done = self.db.done_hours_by_topic()
        sessions = self.db.sessions()
        stats = []
        for sub in self.db.subjects():
            topics = self.db.topics(sub["id"])
            factor = weakness_factor(sub["weakness"])
            target = sum(t["est_hours"] * factor for t in topics)
            studied = 0.0
            for t in topics:
                # A topic ticked off as complete counts as fully studied.
                studied += t["est_hours"] * factor if t["completed"] else min(done.get(t["id"], 0.0),
                                                                               t["est_hours"] * factor)
            mine = [s for s in sessions if s["subject_id"] == sub["id"]]
            planned_past = sum(s["hours"] for s in mine if s["status"] != "planned"
                               and date.fromisoformat(s["date"]) < today)
            done_past = sum(s["actual_hours"] for s in mine if s["status"] == "done"
                            and date.fromisoformat(s["date"]) < today)
            missed = [s for s in mine if s["status"] == "missed"]
            stats.append({
                "subject_id": sub["id"],
                "subject": sub["name"],
                "exam_date": sub["exam_date"],
                "days_left": (date.fromisoformat(sub["exam_date"]) - today).days,
                "weakness": sub["weakness"],
                "target_hours": round(target, 1),
                "studied_hours": round(studied, 1),
                "progress": studied / target if target else 0.0,
                "missed_sessions": len(missed),
                "missed_hours": round(sum(s["hours"] for s in missed), 1),
                "adherence": done_past / planned_past if planned_past else None,
                "topics_done": sum(1 for t in topics if t["completed"]),
                "topics_total": len(topics),
            })
        return stats
