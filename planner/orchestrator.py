"""Coordinates the four agents. `run_cycle` is called on every app load: the
Progress Tracker looks for sessions that slipped by, and if it finds any the
Schedule Optimizer reorganizes the rest of the plan automatically."""
from __future__ import annotations

import json
from datetime import date

from planner import llm
from planner.agents import syllabus_analyzer
from planner.agents.progress_tracker import ProgressTracker
from planner.agents.schedule_optimizer import ScheduleOptimizer
from planner.db import Database

COACH_SYSTEM = """You are a supportive, practical study coach inside a study-planner
app. You get the student's progress data as JSON. Write a short briefing in
Markdown (under 200 words): what to focus on today and why, any subject at risk
of running out of time (with a concrete fix such as adding hours on a specific
weekday or ticking off topics they already know), and one tip for the weakest
subject. Be specific and use the numbers. No preamble."""


class Orchestrator:
    def __init__(self, db: Database):
        self.db = db
        self.tracker = ProgressTracker(db)
        self.optimizer = ScheduleOptimizer(db, self.tracker)

    def run_cycle(self, today: date) -> list[dict]:
        missed = self.tracker.sweep_overdue(today)
        if missed:
            self.optimizer.replan(today, f"{len(missed)} missed session(s) redistributed")
        elif self.db.subjects() and not self.db.sessions(today, status="planned") and self._work_left(today):
            self.optimizer.replan(today, "no upcoming sessions found")
        return missed

    def _work_left(self, today: date) -> bool:
        from planner.agents.planner import topic_targets
        subjects = [s for s in self.db.subjects() if date.fromisoformat(s["exam_date"]) > today]
        return bool(topic_targets(subjects, self.db.topics(), self.db.done_hours_by_topic()))

    # --- user actions -------------------------------------------------
    def analyze_syllabus(self, subject: str, syllabus: str, exam_date: date) -> tuple[list[dict], str]:
        settings = self.db.get_settings()
        llm.configure(settings)
        topics, note = syllabus_analyzer.analyze(subject, syllabus, exam_date, settings["use_llm"])
        self.db.log("Syllabus Analyzer", f"{subject}: extracted {len(topics)} topics, "
                                         f"{sum(t['est_hours'] for t in topics):g}h estimated. {note}")
        return topics, note

    def add_subject(self, name: str, exam_date: date, weakness: int, syllabus: str, topics: list[dict],
                    today: date) -> None:
        revision_pct = self.db.get_settings()["revision_pct"]
        self.db.add_subject(name, exam_date, weakness, syllabus,
                            syllabus_analyzer.with_revision(topics, revision_pct))
        self.db.log("Planner", f"Added {name} (exam {exam_date.isoformat()}, weakness {weakness}/5).")
        self.optimizer.replan(today, f"new subject {name}")

    def complete_session(self, session: dict, actual_hours: float, today: date) -> None:
        self.tracker.complete(session, actual_hours)
        if abs(actual_hours - session["hours"]) >= 0.25:
            self.optimizer.replan(today, f"studied {actual_hours:g}h instead of {session['hours']:g}h")

    def miss_session(self, session: dict, today: date) -> None:
        self.tracker.miss(session)
        self.optimizer.replan(today, f"missed '{session['topic']}'")

    def coach_briefing(self, today: date) -> str:
        stats = self.tracker.subject_stats(today)
        todays = self.db.sessions(today, today)
        shortfall = self.optimizer.feasibility(today)
        names = {s["subject_id"]: s["subject"] for s in stats}
        payload = {
            "today": today.isoformat(),
            "subjects": stats,
            "today_sessions": [{k: s[k] for k in ("subject", "topic", "hours", "status")} for s in todays],
            "unschedulable_hours": {names.get(k, k): v for k, v in shortfall.items()},
            "weekday_hours": self.db.get_settings()["weekday_hours"],
        }
        settings = self.db.get_settings()
        llm.configure(settings)
        if settings["use_llm"]:
            try:
                return llm.complete_text(COACH_SYSTEM, json.dumps(payload, indent=1, default=str))
            except llm.LLMUnavailable as e:
                return f"_AI unavailable ({e}). Rule-based briefing:_\n\n" + self._rule_briefing(payload)
        return self._rule_briefing(payload)

    @staticmethod
    def _rule_briefing(p: dict) -> str:
        lines = []
        if p["today_sessions"]:
            lines.append("**Today:** " + "; ".join(f"{s['subject']} – {s['topic']} ({s['hours']:g}h)"
                                                   for s in p["today_sessions"] if s["status"] != "missed"))
        else:
            lines.append("**Today:** nothing scheduled. Rest, or get ahead on your weakest subject.")
        for name, h in p["unschedulable_hours"].items():
            lines.append(f"- ⚠️ **{name}** is {h:g}h short before its exam. Add hours on a weekday or "
                         f"tick off topics you already know.")
        active = [s for s in p["subjects"] if s["days_left"] > 0]
        if active:
            weakest = max(active, key=lambda s: (s["weakness"], -s["progress"]))
            lines.append(f"- Weakest subject: **{weakest['subject']}**, {weakest['progress']:.0%} done, "
                         f"{weakest['days_left']} days left. Use active recall and past papers there.")
            behind = [s for s in active if s["missed_sessions"]]
            for s in behind:
                lines.append(f"- {s['subject']}: {s['missed_sessions']} missed session(s) "
                             f"({s['missed_hours']:g}h) were moved into later days.")
        return "\n".join(lines)
