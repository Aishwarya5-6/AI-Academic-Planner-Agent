"""Planner tools: the actions an LLM agent may take on the study plan.

Each function returns a JSON-serialisable dict. They are exposed to models via
the MCP server (`mcp_server.py`), which the in-app Study Assistant and any
external MCP client (Claude Desktop, Claude Code, ...) connect to."""
from __future__ import annotations

from datetime import date, timedelta

from planner.db import Database
from planner.orchestrator import Orchestrator

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class ToolError(ValueError):
    pass


class PlannerTools:
    def __init__(self, db: Database, today: date):
        self.db = db
        self.today = today
        self.orch = Orchestrator(db)

    # --- helpers ---------------------------------------------------------
    def _subject(self, name: str) -> dict:
        subjects = self.db.subjects()
        exact = [s for s in subjects if s["name"].lower() == name.strip().lower()]
        partial = [s for s in subjects if name.strip().lower() in s["name"].lower()]
        match = exact or partial
        if len(match) != 1:
            raise ToolError(f"Unknown or ambiguous subject '{name}'. Subjects: "
                            + ", ".join(s["name"] for s in subjects))
        return match[0]

    def _session(self, session_id: int) -> dict:
        found = [s for s in self.db.sessions() if s["id"] == session_id]
        if not found:
            raise ToolError(f"No session with id {session_id}")
        return found[0]

    @staticmethod
    def _fmt(s: dict) -> dict:
        return {"session_id": s["id"], "date": s["date"], "subject": s["subject"], "topic": s["topic"],
                "planned_hours": s["hours"], "status": s["status"]}

    # --- read tools ----------------------------------------------------------
    def get_schedule(self, start_date: str | None = None, days: int = 7) -> dict:
        start = date.fromisoformat(start_date) if start_date else self.today
        days = max(1, min(int(days), 60))
        sessions = self.db.sessions(start, start + timedelta(days=days - 1))
        return {"today": self.today.isoformat(), "sessions": [self._fmt(s) for s in sessions]}

    def get_progress(self) -> dict:
        stats = self.orch.tracker.subject_stats(self.today)
        shortfall = self.orch.optimizer.feasibility(self.today)
        names = {s["subject_id"]: s["subject"] for s in stats}
        return {"today": self.today.isoformat(), "subjects": stats,
                "hours_that_cannot_fit_before_exam": {names[k]: v for k, v in shortfall.items()}}

    def list_subjects(self) -> dict:
        out = []
        done = self.db.done_hours_by_topic()
        for s in self.db.subjects():
            out.append({"subject": s["name"], "exam_date": s["exam_date"], "weakness": s["weakness"],
                        "topics": [{"topic": t["name"], "est_hours": t["est_hours"], "difficulty": t["difficulty"],
                                    "studied_hours": done.get(t["id"], 0), "completed": bool(t["completed"])}
                                   for t in self.db.topics(s["id"])]})
        return {"subjects": out, "availability_hours": self._availability()}

    def _availability(self) -> dict:
        hours = self.db.get_settings()["weekday_hours"]
        return {WEEKDAYS[int(k)]: v for k, v in sorted(hours.items())}

    # --- write tools (each one replans) --------------------------------------
    def log_study_session(self, session_id: int, hours_studied: float) -> dict:
        s = self._session(session_id)
        if s["status"] != "planned":
            raise ToolError(f"Session {session_id} is already {s['status']}")
        if hours_studied <= 0:
            self.orch.miss_session(s, self.today)
            return {"ok": True, "result": "marked missed, schedule reorganized"}
        self.orch.complete_session(s, float(hours_studied), self.today)
        return {"ok": True, "result": f"logged {hours_studied:g}h on '{s['topic']}'"}

    def mark_session_missed(self, session_id: int) -> dict:
        s = self._session(session_id)
        if s["status"] != "planned":
            raise ToolError(f"Session {session_id} is already {s['status']}")
        self.orch.miss_session(s, self.today)
        return {"ok": True, "result": "marked missed; remaining schedule reorganized"}

    def mark_topic_mastered(self, subject: str, topic: str, mastered: bool = True) -> dict:
        sub = self._subject(subject)
        topics = [t for t in self.db.topics(sub["id"]) if topic.strip().lower() in t["name"].lower()]
        if len(topics) != 1:
            raise ToolError(f"Topic '{topic}' not found uniquely in {sub['name']}. Topics: "
                            + ", ".join(t["name"] for t in self.db.topics(sub["id"])))
        self.db.set_topic_completed(topics[0]["id"], mastered)
        self.db.log("Assistant", f"Topic '{topics[0]['name']}' marked {'mastered' if mastered else 'not mastered'}.")
        self.orch.optimizer.replan(self.today, f"topic '{topics[0]['name']}' updated via assistant")
        return {"ok": True, "topic": topics[0]["name"], "mastered": mastered}

    def set_availability(self, weekday: str, hours: float) -> dict:
        day = weekday.strip().lower()
        if day not in WEEKDAYS:
            raise ToolError(f"weekday must be one of {WEEKDAYS}")
        if not 0 <= hours <= 16:
            raise ToolError("hours must be between 0 and 16")
        settings = self.db.get_settings()
        settings["weekday_hours"][str(WEEKDAYS.index(day))] = float(hours)
        self.db.save_settings(settings)
        result = self.orch.optimizer.replan(self.today, f"{day} availability set to {hours:g}h via assistant")
        return {"ok": True, "availability_hours": self._availability(),
                "subjects_still_short": len(result.shortfall)}

    def update_subject(self, subject: str, exam_date: str | None = None, weakness: int | None = None) -> dict:
        sub = self._subject(subject)
        new_exam = date.fromisoformat(exam_date) if exam_date else date.fromisoformat(sub["exam_date"])
        new_weak = int(weakness) if weakness is not None else sub["weakness"]
        if not 1 <= new_weak <= 5:
            raise ToolError("weakness must be 1-5")
        self.db.update_subject(sub["id"], new_exam, new_weak)
        self.orch.optimizer.replan(self.today, f"{sub['name']} updated via assistant")
        return {"ok": True, "subject": sub["name"], "exam_date": new_exam.isoformat(), "weakness": new_weak}

    def reoptimize_schedule(self, reason: str = "requested by assistant") -> dict:
        result = self.orch.optimizer.replan(self.today, reason)
        return {"ok": True, "sessions": len(result.sessions),
                "total_hours": sum(h for *_, h in result.sessions),
                "subjects_short_of_time": len(result.shortfall)}
