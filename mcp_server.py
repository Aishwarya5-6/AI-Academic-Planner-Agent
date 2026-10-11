"""MCP server exposing the study planner's tools.

Used by the in-app Study Assistant (over stdio), and can be added to any MCP
client, e.g.:
    claude mcp add study-planner -- /path/to/.venv/bin/python /path/to/mcp_server.py

Environment:
    PLANNER_DB     SQLite path (defaults to data/planner.db, shared with the app)
    PLANNER_TODAY  ISO date to treat as "today" (the app passes its simulated date)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402

from planner.db import DEFAULT_DB_PATH, Database  # noqa: E402
from planner.tools import PlannerTools  # noqa: E402

READ_ONLY = ToolAnnotations(readOnlyHint=True)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False)


def _tools() -> PlannerTools:
    # Fresh connection per call so the server always sees what the app just wrote.
    today = date.fromisoformat(os.environ["PLANNER_TODAY"]) if os.environ.get("PLANNER_TODAY") else date.today()
    return PlannerTools(Database(os.environ.get("PLANNER_DB", DEFAULT_DB_PATH)), today)


def _run(method: str, *args):
    """Call a planner tool; bad input (unknown id, bad date, ...) goes back to the model as a tool error."""
    try:
        return getattr(_tools(), method)(*args)
    except ValueError as e:  # includes planner.tools.ToolError
        raise ToolError(str(e)) from e


def build_server() -> MCPServer:
    mcp = MCPServer(
        "study-planner",
        instructions="Tools for a student's exam study plan: read the schedule and progress, log or miss "
                     "sessions, mark mastered topics, change availability or exam dates. Every change "
                     "automatically reorganizes the remaining schedule.",
    )

    @mcp.tool(annotations=READ_ONLY)
    def get_schedule(start_date: str | None = None, days: int = 7) -> dict:
        """Study sessions from start_date (YYYY-MM-DD, default today) for `days` days, with session_id,
        subject, topic, planned hours and status (planned/done/missed)."""
        return _run("get_schedule", start_date, days)

    @mcp.tool(annotations=READ_ONLY)
    def get_progress() -> dict:
        """Per-subject progress: hours studied vs target, days to exam, missed sessions, adherence,
        and any hours that cannot fit before an exam."""
        return _run("get_progress")

    @mcp.tool(annotations=READ_ONLY)
    def list_subjects() -> dict:
        """All subjects with exam dates, weakness (1-5), topics and the weekly study-hour availability."""
        return _run("list_subjects")

    @mcp.tool(annotations=WRITES)
    def log_study_session(session_id: int, hours_studied: float) -> dict:
        """Record that the student studied a planned session (use the actual hours; less than planned
        triggers a replan). Get session_id from get_schedule."""
        return _run("log_study_session", session_id, hours_studied)

    @mcp.tool(annotations=WRITES)
    def mark_session_missed(session_id: int) -> dict:
        """Mark a planned session as missed. Its hours are redistributed over the remaining days."""
        return _run("mark_session_missed", session_id)

    @mcp.tool(annotations=WRITES)
    def mark_topic_mastered(subject: str, topic: str, mastered: bool = True) -> dict:
        """Mark a topic as already mastered (removes its remaining hours from the plan), or un-mark it.
        Subject and topic may be partial names."""
        return _run("mark_topic_mastered", subject, topic, mastered)

    @mcp.tool(annotations=WRITES)
    def set_availability(weekday: str, hours: float) -> dict:
        """Set how many hours the student can study on a weekday (e.g. 'saturday', 6)."""
        return _run("set_availability", weekday, hours)

    @mcp.tool(annotations=WRITES)
    def update_subject(subject: str, exam_date: str | None = None, weakness: int | None = None) -> dict:
        """Change a subject's exam date (YYYY-MM-DD) and/or weakness rating (1 strong - 5 weak)."""
        return _run("update_subject", subject, exam_date, weakness)

    @mcp.tool(annotations=WRITES)
    def reoptimize_schedule(reason: str = "requested") -> dict:
        """Rebuild the remaining schedule from scratch from what is left to study."""
        return _run("reoptimize_schedule", reason)

    @mcp.resource("planner://today", mime_type="application/json")
    def today_plan() -> str:
        """Today's study sessions."""
        t = _tools()
        return json.dumps(t.get_schedule(t.today.isoformat(), 1))

    @mcp.prompt()
    def daily_briefing() -> str:
        """Ask the model for a study briefing for today."""
        return ("Use get_schedule and get_progress, then give me a short briefing: what to study today, "
                "which subject is at risk, and one concrete fix.")

    return mcp


if __name__ == "__main__":
    build_server().run(transport="stdio")
