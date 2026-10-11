"""Small HTML building blocks rendered with st.html. All text is escaped."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape

import streamlit as st

# Validated categorical palette, assigned to subjects in fixed order by subject id.
SUBJECT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]

AGENTS = {
    "Syllabus Analyzer": ("document_scanner", "#2a78d6", "Breaks a syllabus into topics with hours and difficulty."),
    "Planner": ("event_note", "#1baf7a", "Spreads study hours across days before each exam."),
    "Progress Tracker": ("monitoring", "#eb6834", "Logs study, detects missed sessions, tracks progress."),
    "Schedule Optimizer": ("auto_mode", "#6250d6", "Reorganizes the plan whenever reality changes."),
    "Assistant": ("smart_toy", "#e87ba4", "Chat agent that acts on your plan through MCP tools."),
}


def icon(name: str, style: str = "") -> str:
    return f'<span class="msr" style="{style}">{escape(name)}</span>'


def html(markup: str) -> None:
    st.html(markup)


def section(title: str, icon_name: str, sub: str = "") -> None:
    html(f'<div class="section-title">{icon(icon_name)}{escape(title)}'
         f'{f"<span class=sub>{escape(sub)}</span>" if sub else ""}</div>')


def empty(icon_name: str, title: str, text: str) -> None:
    html(f'<div class="card empty">{icon(icon_name)}<div class="t">{escape(title)}</div>'
         f'<div class="muted">{escape(text)}</div></div>')


def tint(color: str, pct: int = 14) -> str:
    return f"color-mix(in srgb, {color} {pct}%, transparent)"


def hero(today: date, planned_h: float, done_h: float, next_exam: tuple[str, int] | None, streak: int) -> None:
    hour = datetime.now().hour
    greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    if planned_h + done_h == 0:
        line = "No study sessions today. Rest up, or get ahead on a weak subject."
    elif planned_h == 0:
        line = "You've finished everything planned for today. Great work."
    else:
        line = f"{planned_h:g} hours of focused study planned today. One session at a time."
    exam_v = f"{next_exam[1]}d" if next_exam else "–"
    exam_k = "Next exam"
    exam_sub = (f'<div style="font-size:.74rem;opacity:.8;max-width:150px;white-space:nowrap;overflow:hidden;'
                f'text-overflow:ellipsis">{escape(next_exam[0])}</div>') if next_exam else ""
    html(f"""
    <div class="hero">
      <div style="position:relative;z-index:1;max-width:520px">
        <div class="eyebrow">{icon('calendar_today')} {today:%A, %d %B}</div>
        <h1>{greet}</h1>
        <p>{escape(line)}</p>
      </div>
      <div class="hero-stats">
        <div class="hero-chip"><div class="k">Today</div><div class="v">{done_h:g}<span style="opacity:.7;font-size:.9rem"> / {done_h + planned_h:g}h</span></div></div>
        <div class="hero-chip"><div class="k">{exam_k}</div><div class="v">{exam_v}</div>{exam_sub}</div>
        <div class="hero-chip"><div class="k">Streak</div><div class="v">{streak} {icon('local_fire_department', 'font-size:1.1em')}</div></div>
      </div>
    </div>""")


def session_card(s: dict, color: str) -> str:
    status = {"planned": ("chip", "schedule", "Planned"), "done": ("chip good", "check_circle", "Done"),
              "missed": ("chip bad", "event_busy", "Missed")}[s["status"]]
    kind = "Revision" if s.get("is_revision") else "Study"
    hours = f'{s["actual_hours"]:g}h studied' if s["status"] == "done" else f'{s["hours"]:g}h'
    return f"""
    <div class="session">
      <div class="icon" style="background:{tint(color, 16)};color:{color}">{icon('history_edu' if s.get('is_revision') else 'menu_book')}</div>
      <div style="min-width:0">
        <div class="subject" style="color:{color}">{escape(s['subject'])}</div>
        <div class="topic">{escape(s['topic'])}</div>
        <div class="meta"><span class="chip">{icon('timer')} {hours}</span><span class="chip">{kind}</span>
          <span class="{status[0]}">{icon(status[1])} {status[2]}</span></div>
      </div>
    </div>"""


def week_strip(today: date, sessions: list[dict], exams: dict[str, str], color_of: dict[str, str]) -> None:
    by_day: dict[str, list[dict]] = {}
    for s in sessions:
        by_day.setdefault(s["date"], []).append(s)
    max_h = max([sum(x["hours"] for x in v) for v in by_day.values()] + [1])
    cells = []
    for i in range(7):
        d = today + timedelta(days=i)
        items = by_day.get(d.isoformat(), [])
        total = sum(x["hours"] for x in items if x["status"] != "missed")
        segs = "".join(f'<span style="height:{x["hours"] / max_h * 100:.0f}%;background:{color_of.get(x["subject"], "#888")}"'
                       f' title="{escape(x["subject"])}: {x["hours"]:g}h"></span>'
                       for x in items if x["status"] != "missed")
        exam = [n for n, ed in exams.items() if ed == d.isoformat()]
        cells.append(f'<div class="day {"today" if i == 0 else ""}"><div class="dn">{"Today" if i == 0 else f"{d:%a}"}</div>'
                     f'<div class="dd">{d.day}</div><div class="stack">{segs}</div>'
                     f'<div class="h">{total:g}h</div>'
                     + (f'<div class="exam">{icon("flag")} Exam</div>' if exam else "") + "</div>")
    html(f'<div class="week">{"".join(cells)}</div>')


def exam_cards(stats: list[dict], color_of: dict[str, str]) -> None:
    cards = []
    for s in sorted(stats, key=lambda s: s["days_left"]):
        if s["days_left"] < 0:
            continue
        c = color_of.get(s["subject"], "#888")
        risk = "bad" if s["days_left"] <= 3 and s["progress"] < .7 else "warn" if s["progress"] < .4 and s["days_left"] <= 10 else "good"
        label = {"bad": "At risk", "warn": "Behind", "good": "On track"}[risk]
        cards.append(f"""<div class="card exam-card"><div class="glow" style="background:{c}"></div>
          <div class="big">{s['days_left']}<span style="font-size:.95rem;font-weight:600" class="muted"> days</span></div>
          <div class="name">{escape(s['subject'])}</div>
          <div class="muted" style="font-size:.8rem;margin:2px 0 10px">{date.fromisoformat(s['exam_date']):%a %d %b}</div>
          <div class="pbar"><span style="width:{min(100, s['progress'] * 100):.0f}%;background:{c}"></span></div>
          <div style="display:flex;justify-content:space-between;margin-top:8px;font-size:.8rem">
            <span class="muted">{s['progress']:.0%} ready</span><span class="chip {risk}">{label}</span></div></div>""")
    html(f'<div class="exams">{"".join(cards)}</div>' if cards else "")


def ring_card(s: dict, color: str) -> str:
    pct = min(100, s["progress"] * 100)
    adher = f"{s['adherence']:.0%}" if s["adherence"] is not None else "–"
    weak = "".join(f'<i style="{"background:" + color if i < s["weakness"] else ""}"></i>' for i in range(5))
    return f"""<div class="card ring-card">
      <div class="ringw"><div class="ring" style="--p:{pct:.0f};--c:{color}"></div><div class="val">{pct:.0f}%</div></div>
      <div style="min-width:0;flex:1">
        <div style="font-weight:700;font-size:1.02rem">{escape(s['subject'])}</div>
        <div class="muted" style="font-size:.84rem;margin:2px 0 8px">{s['studied_hours']:g} of {s['target_hours']:g} hours · {s['topics_done']}/{s['topics_total']} topics mastered</div>
        <div class="meta" style="display:flex;gap:6px;flex-wrap:wrap">
          <span class="chip">{icon('event')} {max(s['days_left'], 0)} days left</span>
          <span class="chip">{icon('task_alt')} adherence {adher}</span>
          <span class="chip {'bad' if s['missed_sessions'] else ''}">{icon('event_busy')} {s['missed_sessions']} missed</span>
          <span class="chip">weakness <span class="weak">{weak}</span></span>
        </div>
      </div></div>"""


def timeline(sessions: list[dict], exams: dict[str, list[str]], color_of: dict[str, str], today: date) -> None:
    days: dict[str, list[dict]] = {}
    for s in sessions:
        days.setdefault(s["date"], []).append(s)
    for d in exams:
        days.setdefault(d, [])
    rows = []
    for d in sorted(days):
        dd = date.fromisoformat(d)
        items = "".join(
            f'<div class="tl-item {s["status"]}"><span class="dot" style="background:{color_of.get(s["subject"], "#888")}"></span>'
            f'<span class="t">{escape(s["topic"])}</span><span class="s">{escape(s["subject"])}</span>'
            f'<span class="chip">{s["hours"]:g}h</span></div>' for s in days[d])
        items += "".join(f'<div class="tl-exam">{icon("flag")} {escape(n)} exam</div>' for n in exams.get(d, []))
        label = "Today" if dd == today else "Tomorrow" if dd == today + timedelta(days=1) else f"{dd:%a}"
        rows.append(f'<div class="tl-day"><div class="tl-date"><div class="dn">{label}</div><div class="dd">{dd.day}</div>'
                    f'<div class="mm">{dd:%b}</div></div><div class="tl-items">{items}</div></div>')
    html(f'<div>{"".join(rows)}</div>')


def subject_header(s: dict, color: str, days_left: int, progress: float, topics: list[dict]) -> None:
    weak = "".join(f'<i style="{"background:" + color if i < s["weakness"] else ""}"></i>' for i in range(5))
    initials = "".join(w[0] for w in s["name"].replace("&", " ").split()[:2]).upper()
    chips = "".join(f'<span class="chip {"done" if t["completed"] else ""}">'
                    f'{icon("check") if t["completed"] else ""}{escape(t["name"][:38])}</span>' for t in topics)
    when = f"{days_left} days left" if days_left >= 0 else "Exam passed"
    html(f"""<div>
      <div class="subj-head"><div class="badge" style="background:{color}">{escape(initials)}</div>
        <div style="flex:1;min-width:0"><div class="n">{escape(s['name'])}</div>
          <div class="muted" style="font-size:.82rem">{icon('event')} {date.fromisoformat(s['exam_date']):%d %b %Y} · {when}</div></div>
        <div style="text-align:right"><div class="muted" style="font-size:.72rem">WEAKNESS</div><span class="weak">{weak}</span></div></div>
      <div style="display:flex;align-items:center;gap:10px;margin-top:14px">
        <div class="pbar" style="flex:1"><span style="width:{min(100, progress * 100):.0f}%;background:{color}"></span></div>
        <span style="font-weight:700;font-size:.85rem">{progress:.0%}</span></div>
      <div class="topics">{chips}</div></div>""")


def agent_cards(last: dict[str, str]) -> None:
    cards = "".join(f"""<div class="card agent"><div class="ic" style="background:{c}">{icon(i)}</div>
        <div class="n">{escape(n)}</div><div class="r">{escape(r)}</div>
        <div class="last">{icon('history')} {escape(last.get(n, 'No activity yet'))}</div></div>"""
                    for n, (i, c, r) in AGENTS.items())
    html(f'<div class="agents">{cards}</div>')


def feed(entries: list[dict]) -> None:
    items = []
    for e in entries:
        i, c, _ = AGENTS.get(e["agent"], ("bolt", "#888", ""))
        when = e["ts"].replace("T", " ")[5:16]
        items.append(f'<div class="feed-item"><div class="ic" style="background:{c}">{icon(i)}</div><div>'
                     f'<div class="who">{escape(e["agent"])}<span class="when">{escape(when)}</span></div>'
                     f'<div class="what">{escape(e["message"])}</div></div></div>')
    html(f'<div class="feed">{"".join(items)}</div>')


MCP_TOOLS = [("get_schedule", "calendar_month"), ("get_progress", "insights"), ("list_subjects", "menu_book"),
             ("log_study_session", "timer"), ("mark_session_missed", "event_busy"),
             ("mark_topic_mastered", "verified"), ("set_availability", "schedule"),
             ("update_subject", "edit_calendar"), ("reoptimize_schedule", "autorenew")]


def assistant_intro() -> None:
    tools = "".join(f'<span class="chip">{icon(i)} {n}</span>' for n, i in MCP_TOOLS)
    html(f"""<div class="card intro"><div><div class="orb">{icon('smart_toy')}</div>
      <div class="big">Tell me what happened, and I'll fix your plan.</div>
      <div class="muted" style="margin-top:6px">I'm connected to the planner's MCP server, so I can check your
      schedule, log study, handle missed sessions and change availability. Just ask in plain words.</div></div>
      <div><div class="muted" style="font-size:.78rem;font-weight:600;letter-spacing:.06em;margin-bottom:8px">
      {icon('build')} MCP TOOLS AVAILABLE</div><div class="tools">{tools}</div></div></div>""")
