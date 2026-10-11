"""Syllabus Analyzer agent: turns raw syllabus text into topics with an hour
estimate and difficulty rating. Uses the configured LLM when available, otherwise a
line-based heuristic parser."""
from __future__ import annotations

import re
from datetime import date

from planner import llm

TOPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "est_hours": {"type": "number"},
                    "difficulty": {"type": "integer"},
                },
                "required": ["name", "est_hours", "difficulty"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["topics", "notes"],
    "additionalProperties": False,
}

SYSTEM = """You are the Syllabus Analyzer in a study-planning system. You break a
course syllabus into study topics that a student can schedule.

For each topic give:
- name: short and specific (e.g. "Eigenvalues & diagonalization", not "Unit 3").
- est_hours: realistic self-study hours for a typical student to learn it well
  enough for the exam, including practice problems (usually 1-8 hours).
- difficulty: 1 (easy) to 5 (very hard).

Keep the syllabus order, since earlier topics are usually prerequisites. Merge
trivial items and split units that are too large to study in one sitting.
Aim for 4-20 topics. Do not add a revision topic; the planner adds one.
Put any caveats in `notes` (one or two sentences)."""

HARD_HINTS = ("advanced", "theorem", "proof", "derivation", "differential", "integral",
              "algorithm", "dynamic programming", "quantum", "thermodynamics", "complex")
EASY_HINTS = ("introduction", "intro", "overview", "basics", "basic", "fundamentals")


def heuristic_topics(syllabus: str, default_hours: float = 3.0) -> list[dict]:
    lines = [ln for ln in re.split(r"[\n;]+", syllabus) if ln.strip()]
    if len(lines) == 1 and "," in lines[0]:
        lines = lines[0].split(",")
    topics = []
    for ln in lines:
        # Strip bullets and numbering like "1.", "-", "•", "Unit 2:", "Module III -"
        name = re.sub(r"^\s*([-*•]+|\d+[.)]|(unit|module|chapter)\s*[\divx]+\s*[:.\-]?)\s*", "", ln,
                      flags=re.IGNORECASE).strip(" .:-")
        if len(name) < 2:
            continue
        low = name.lower()
        difficulty = 3
        if any(h in low for h in HARD_HINTS):
            difficulty = 4
        elif any(h in low for h in EASY_HINTS):
            difficulty = 2
        # Longer lines usually describe more sub-content.
        hours = default_hours * (0.7 + 0.15 * difficulty) * (1.25 if len(name) > 60 else 1.0)
        topics.append({"name": name[:120], "est_hours": round(hours * 2) / 2, "difficulty": difficulty})
    return topics


def analyze(subject: str, syllabus: str, exam_date: date, use_llm: bool = True) -> tuple[list[dict], str]:
    """Return (topics, note). Falls back to the heuristic parser if no LLM is available."""
    if use_llm and llm.is_configured():
        prompt = (f"Subject: {subject}\nExam date: {exam_date.isoformat()}\n\n"
                  f"<syllabus>\n{syllabus}\n</syllabus>")
        try:
            result = llm.complete_json(SYSTEM, prompt, TOPIC_SCHEMA)
            topics = [
                {"name": t["name"].strip()[:120],
                 "est_hours": max(0.5, min(float(t["est_hours"]), 40.0)),
                 "difficulty": max(1, min(int(t["difficulty"]), 5))}
                for t in result["topics"] if t["name"].strip()
            ]
            if topics:
                return topics, f"Analyzed with {llm.describe()}. {result.get('notes', '')}".strip()
        except llm.LLMUnavailable as e:
            return heuristic_topics(syllabus), f"AI unavailable ({e}); used the offline parser."
    return heuristic_topics(syllabus), "Used the offline parser (one topic per line). Edit the hours below."


def with_revision(topics: list[dict], revision_pct: float) -> list[dict]:
    total = sum(t["est_hours"] for t in topics)
    hours = max(1.0, round(total * revision_pct / 100 * 2) / 2)
    return topics + [{"name": "Final revision & past papers", "est_hours": hours, "difficulty": 3,
                      "is_revision": 1}]
