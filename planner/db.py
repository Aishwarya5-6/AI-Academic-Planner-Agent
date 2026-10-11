"""SQLite persistence for subjects, topics, study sessions, settings and the agent log."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Iterator

DEFAULT_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "planner.db")

DEFAULT_SETTINGS: dict[str, Any] = {
    # Study hours available per weekday (0 = Monday ... 6 = Sunday)
    "weekday_hours": {"0": 3.0, "1": 3.0, "2": 3.0, "3": 3.0, "4": 2.0, "5": 5.0, "6": 5.0},
    "session_length": 1.5,  # hours per study block
    "revision_pct": 15,  # % of a subject's hours reserved for a final revision block
    "use_llm": True,
    "llm_provider": "auto",  # auto | groq | gemini | openrouter | ollama | anthropic
    "llm_models": {},  # provider -> model override
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    exam_date TEXT NOT NULL,
    weakness INTEGER NOT NULL DEFAULT 3,
    syllabus TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    est_hours REAL NOT NULL,
    difficulty INTEGER NOT NULL DEFAULT 3,
    position INTEGER NOT NULL DEFAULT 0,
    is_revision INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    hours REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned',  -- planned | done | missed
    actual_hours REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    agent TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_date ON sessions(date);
"""


class Database:
    def __init__(self, path: str = DEFAULT_DB_PATH):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._conn:
            yield self._conn

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    # --- settings -------------------------------------------------------
    def get_settings(self) -> dict[str, Any]:
        settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        for row in self.query("SELECT key, value FROM settings"):
            settings[row["key"]] = json.loads(row["value"])
        return settings

    def save_settings(self, settings: dict[str, Any]) -> None:
        with self.tx() as c:
            for k, v in settings.items():
                c.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (k, json.dumps(v)),
                )

    # --- subjects & topics ---------------------------------------------
    def add_subject(self, name: str, exam_date: date, weakness: int, syllabus: str,
                    topics: list[dict]) -> int:
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO subjects(name, exam_date, weakness, syllabus, created_at) VALUES(?,?,?,?,?)",
                (name, exam_date.isoformat(), weakness, syllabus, datetime.now().isoformat()),
            )
            subject_id = cur.lastrowid
            for i, t in enumerate(topics):
                c.execute(
                    "INSERT INTO topics(subject_id, name, est_hours, difficulty, position, is_revision) "
                    "VALUES(?,?,?,?,?,?)",
                    (subject_id, t["name"], float(t["est_hours"]), int(t.get("difficulty", 3)), i,
                     int(t.get("is_revision", 0))),
                )
        return subject_id

    def update_subject(self, subject_id: int, exam_date: date, weakness: int) -> None:
        with self.tx() as c:
            c.execute("UPDATE subjects SET exam_date = ?, weakness = ? WHERE id = ?",
                      (exam_date.isoformat(), weakness, subject_id))

    def delete_subject(self, subject_id: int) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM subjects WHERE id = ?", (subject_id,))

    def subjects(self) -> list[dict]:
        return self.query("SELECT * FROM subjects ORDER BY exam_date, id")

    def topics(self, subject_id: int | None = None) -> list[dict]:
        if subject_id is None:
            return self.query("SELECT * FROM topics ORDER BY subject_id, is_revision, position")
        return self.query("SELECT * FROM topics WHERE subject_id = ? ORDER BY is_revision, position",
                          (subject_id,))

    def set_topic_completed(self, topic_id: int, completed: bool) -> None:
        with self.tx() as c:
            c.execute("UPDATE topics SET completed = ? WHERE id = ?", (int(completed), topic_id))

    # --- sessions ------------------------------------------------------
    def sessions(self, start: date | None = None, end: date | None = None,
                 status: str | None = None) -> list[dict]:
        sql = """SELECT s.*, t.name AS topic, t.subject_id, sub.name AS subject, t.is_revision
                 FROM sessions s JOIN topics t ON t.id = s.topic_id
                 JOIN subjects sub ON sub.id = t.subject_id WHERE 1=1"""
        params: list[Any] = []
        if start:
            sql += " AND s.date >= ?"
            params.append(start.isoformat())
        if end:
            sql += " AND s.date <= ?"
            params.append(end.isoformat())
        if status:
            sql += " AND s.status = ?"
            params.append(status)
        return self.query(sql + " ORDER BY s.date, sub.exam_date, s.id", tuple(params))

    def done_hours_by_topic(self) -> dict[int, float]:
        rows = self.query("SELECT topic_id, SUM(actual_hours) AS h FROM sessions "
                          "WHERE status = 'done' GROUP BY topic_id")
        return {r["topic_id"]: r["h"] or 0.0 for r in rows}

    def set_session_status(self, session_id: int, status: str, actual_hours: float = 0.0) -> None:
        with self.tx() as c:
            c.execute("UPDATE sessions SET status = ?, actual_hours = ? WHERE id = ?",
                      (status, actual_hours, session_id))

    def replace_planned_sessions(self, from_date: date, new_sessions: list[tuple[date, int, float]]) -> int:
        """Drop every still-planned session on/after from_date and insert the new plan."""
        with self.tx() as c:
            removed = c.execute("DELETE FROM sessions WHERE status = 'planned' AND date >= ?",
                                (from_date.isoformat(),)).rowcount
            c.executemany("INSERT INTO sessions(topic_id, date, hours) VALUES(?,?,?)",
                          [(tid, d.isoformat(), round(h, 2)) for d, tid, h in new_sessions])
        return removed

    # --- agent log -----------------------------------------------------
    def log(self, agent: str, message: str) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO agent_log(ts, agent, message) VALUES(?,?,?)",
                      (datetime.now().isoformat(timespec="seconds"), agent, message))

    def recent_log(self, limit: int = 100) -> list[dict]:
        return self.query("SELECT * FROM agent_log ORDER BY id DESC LIMIT ?", (limit,))

    def reset(self) -> None:
        with self.tx() as c:
            for table in ("sessions", "topics", "subjects", "agent_log"):
                c.execute(f"DELETE FROM {table}")
