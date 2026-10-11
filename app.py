"""AI Academic Planner: Streamlit front end.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from planner import llm
from planner.agents import study_assistant
from planner.db import DEFAULT_DB_PATH, Database
from planner.orchestrator import Orchestrator
from planner.sample_data import load_sample
from ui import components as ui
from ui.styles import CSS

st.set_page_config(page_title="Studyflow · AI Academic Planner", page_icon=":material/school:", layout="wide")
st.html(CSS)

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@st.cache_resource
def get_db() -> Database:
    return Database(os.environ.get("PLANNER_DB", DEFAULT_DB_PATH))


db = get_db()
orch = Orchestrator(db)
settings = db.get_settings()

# ===================================================================== sidebar
with st.sidebar:
    st.html(f'<div class="brand"><div class="logo">{ui.icon("school")}</div>'
            '<div><div class="t">Studyflow</div><div class="s">AI academic planner</div></div></div>')
    today = st.date_input("Today", value=date.today(), help="Move this forward to simulate days passing and "
                                                            "watch the agents reorganize your plan.")

    with st.expander("Weekly availability", icon=":material/schedule:", expanded=not db.subjects()):
        new_hours = {str(i): st.slider(d, 0.0, 12.0, float(settings["weekday_hours"][str(i)]), 0.5, key=f"wh{i}")
                     for i, d in enumerate(WEEKDAYS)}
        session_length = st.select_slider("Session length (hours)", [0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
                                          value=float(settings["session_length"]))
        revision_pct = st.slider("Revision buffer for new subjects (%)", 0, 40, int(settings["revision_pct"]), 5)
        if st.button("Save and replan", icon=":material/autorenew:", type="primary", width="stretch"):
            settings.update(weekday_hours=new_hours, session_length=session_length, revision_pct=revision_pct)
            db.save_settings(settings)
            orch.optimizer.replan(today, "availability changed")
            st.rerun()

    use_llm = st.toggle("AI analysis, coach and assistant", value=bool(settings["use_llm"]))
    if use_llm != settings["use_llm"]:
        settings["use_llm"] = use_llm
        db.save_settings(settings)
    llm.configure(settings)
    if use_llm:
        with st.expander("AI model", icon=":material/neurology:", expanded=not llm.is_configured()):
            options = ["auto"] + list(llm.PROVIDERS)
            provider = st.selectbox(
                "Provider", options, index=options.index(settings.get("llm_provider", "auto")),
                format_func=lambda p: "Auto (first provider with a key)" if p == "auto" else llm.PROVIDERS[p].label)
            if provider != settings.get("llm_provider"):
                settings["llm_provider"] = provider
                db.save_settings(settings)
                st.rerun()
            if provider != "auto":
                prov = llm.PROVIDERS[provider]
                models = settings.get("llm_models", {})
                current = models.get(provider) or prov.default_model
                choices = prov.models + ([current] if current not in prov.models else [])
                model = st.selectbox("Model", choices, index=choices.index(current), accept_new_options=True)
                if model != current:
                    settings["llm_models"] = {**models, provider: model}
                    db.save_settings(settings)
                    st.rerun()
                if prov.env_key:
                    st.caption(f"`{prov.env_key}`: {'key saved' if llm.has_key(provider) else 'no key yet'} · "
                               f"[get {'a free' if prov.free else 'a'} key]({prov.signup_url})")
                    key = st.text_input("API key", type="password", key=f"key_{provider}",
                                        placeholder="Paste key, saved to .env")
                    if st.button("Save key", icon=":material/key:", disabled=not key, width="stretch"):
                        llm.save_key(provider, key)
                        st.rerun()
                else:
                    st.caption(f"Runs locally. [Install Ollama]({prov.signup_url}), then `ollama pull {current}`.")
        if llm.is_configured():
            st.badge(llm.describe(), icon=":material/bolt:", color="violet")
        else:
            st.badge("No AI key, using offline rules", icon=":material/cloud_off:", color="orange")

    st.divider()
    c1, c2 = st.columns(2)
    if c1.button("Demo", icon=":material/auto_awesome:", width="stretch", help="Load three sample subjects"):
        load_sample(orch, today)
        st.rerun()
    with c2.popover("Reset", icon=":material/restart_alt:", width="stretch"):
        st.write("Delete all subjects, sessions and history?")
        if st.button("Yes, reset everything", type="primary"):
            db.reset()
            st.rerun()

# ===================================================== autonomous agent cycle
missed = orch.run_cycle(today)
if missed:
    st.toast(f"{len(missed)} missed session(s) detected. Your schedule was reorganized.", icon=":material/autorenew:")

subjects = db.subjects()
color_of = {s["name"]: ui.SUBJECT_COLORS[i % len(ui.SUBJECT_COLORS)]
            for i, s in enumerate(sorted(subjects, key=lambda s: s["id"]))}
exam_by_subject = {s["name"]: s["exam_date"] for s in subjects}


def streak_days() -> int:
    done_days = {s["date"] for s in db.sessions(status="done")}
    n, d = 0, today - timedelta(days=1)
    while d.isoformat() in done_days:
        n, d = n + 1, d - timedelta(days=1)
    return n + (today.isoformat() in done_days)


def need_subjects() -> bool:
    if subjects:
        return False
    ui.empty("school", "Let's build your study plan",
             "Add your first subject with its syllabus and exam date, or try the demo subjects.")
    _, c1, c2, _ = st.columns([1, 1.2, 1.2, 1])
    if c1.button("Add your first subject", icon=":material/add:", type="primary", width="stretch",
                 key=f"empty_add_{st.session_state.get('_page', '')}"):
        add_subject_dialog()
    if c2.button("Load demo subjects", icon=":material/auto_awesome:", width="stretch",
                 key=f"empty_demo_{st.session_state.get('_page', '')}"):
        load_sample(orch, today)
        st.rerun()
    return True


# ======================================================================= pages
def page_today() -> None:
    todays = db.sessions(today, today)
    stats = orch.tracker.subject_stats(today)
    upcoming = [s for s in stats if s["days_left"] > 0]
    nxt = min(upcoming, key=lambda s: s["days_left"]) if upcoming else None
    ui.hero(today, sum(s["hours"] for s in todays if s["status"] == "planned"),
            sum(s["actual_hours"] for s in todays if s["status"] == "done"),
            (nxt["subject"], nxt["days_left"]) if nxt else None, streak_days())
    if need_subjects():
        return

    left, right = st.columns([3, 2], gap="large")
    with left:
        ui.section("Today's sessions", "task_alt", f"{len(todays)} planned")
        if not todays:
            ui.empty("celebration", "Free day", "Nothing scheduled today.")
        for s in todays:
            with st.container(border=True, key=f"sess{s['id']}"):
                ui.html(ui.session_card(s, color_of.get(s["subject"], "#888")))
                if s["status"] == "planned":
                    c1, c2, c3 = st.columns([1.3, 1, 1], vertical_alignment="bottom")
                    actual = c1.number_input("Hours studied", 0.0, 12.0, float(s["hours"]), 0.25, key=f"act{s['id']}")
                    if c2.button("Done", key=f"done{s['id']}", icon=":material/check_circle:", type="primary",
                                 width="stretch"):
                        if actual > 0:
                            orch.complete_session(s, actual, today)
                        else:
                            orch.miss_session(s, today)
                        st.rerun()
                    if c3.button("Missed", key=f"miss{s['id']}", icon=":material/event_busy:", width="stretch"):
                        orch.miss_session(s, today)
                        st.rerun()
    with right:
        ui.section("Exam countdown", "hourglass_top")
        ui.exam_cards(stats, color_of)

    ui.section("This week", "date_range")
    ui.week_strip(today, db.sessions(today, today + timedelta(days=6)), exam_by_subject, color_of)


def page_assistant() -> None:
    ui.section("Study Assistant", "smart_toy", "LLM + MCP tools")
    st.caption("The assistant reads and changes your plan through the planner's MCP server. "
               "Every change reorganizes your schedule automatically.")
    chat_log = st.session_state.setdefault("chat", [])
    if not use_llm or not llm.is_configured():
        ui.empty("key", "Connect an AI model", "Turn on AI in the sidebar and add a free Groq or Gemini key.")
        return

    suggestion = None
    if not chat_log:
        ui.assistant_intro()
        suggestion = st.pills("Try asking", ["What should I study today?", "Am I on track for my exams?",
                                             "I skipped today's first session", "I can study 6 hours on Saturdays now",
                                             "I already know the first topic of my weakest subject"],
                              label_visibility="collapsed")
    for m in chat_log:
        with st.chat_message(m["role"], avatar=":material/person:" if m["role"] == "user" else ":material/smart_toy:"):
            if m.get("tools"):
                with st.expander(f"Used {len(m['tools'])} tool call(s)", icon=":material/build:"):
                    for c in m["tools"]:
                        st.markdown(f"{':material/error:' if c.is_error else ':material/check_circle:'} "
                                    f"`{c.name}({json.dumps(c.arguments)})`")
                        st.code(c.result[:1500], language="json")
            st.markdown(m["content"])

    prompt = st.chat_input("Ask or tell the assistant something…") or suggestion
    if prompt:
        chat_log.append({"role": "user", "content": prompt})
        history = [{"role": m["role"], "content": m["content"]} for m in chat_log[-12:]]
        with st.spinner("Working on it…"):
            try:
                reply = study_assistant.chat(history, today, db.path)
                chat_log.append({"role": "assistant", "content": reply.text or "(no reply)", "tools": reply.tool_calls})
            except llm.LLMUnavailable as e:
                chat_log.append({"role": "assistant", "content": f":material/warning: {e}"})
        st.rerun()
    if chat_log and st.button("New conversation", icon=":material/add_comment:"):
        st.session_state.chat = []
        st.rerun()


def page_plan() -> None:
    ui.section("Study plan", "calendar_month")
    if need_subjects():
        return
    names = {s["id"]: s["name"] for s in subjects}
    for sid, h in orch.optimizer.feasibility(today).items():
        st.warning(f"**{names[sid]}** needs {h:g} more hours than fit before its exam. Add study hours, lower the "
                   f"weakness rating, or mark topics you already know as mastered.", icon=":material/warning:")

    plan = db.sessions(today)
    if not plan:
        ui.empty("event_available", "Nothing left to schedule", "Every topic is covered.")
        return
    df = pd.DataFrame(plan)
    df["date"] = pd.to_datetime(df["date"])
    daily = df[df.status != "missed"].groupby(["date", "subject"], as_index=False)["hours"].sum()
    domain = list(color_of)
    exams = pd.DataFrame([{"date": pd.to_datetime(s["exam_date"]), "subject": s["name"]}
                          for s in subjects if date.fromisoformat(s["exam_date"]) >= today])
    bars = alt.Chart(daily).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
        x=alt.X("yearmonthdate(date):T", title=None, axis=alt.Axis(format="%d %b", grid=False)),
        y=alt.Y("sum(hours):Q", title="Hours", axis=alt.Axis(tickCount=4)),
        color=alt.Color("subject:N", scale=alt.Scale(domain=domain, range=[color_of[n] for n in domain]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=[alt.Tooltip("yearmonthdate(date):T", title="Day"), alt.Tooltip("subject", title="Subject"),
                 alt.Tooltip("hours", title="Hours")])
    rules = alt.Chart(exams).mark_rule(strokeDash=[4, 3], strokeWidth=1.5, color="#dc2626").encode(
        x="yearmonthdate(date):T", tooltip=[alt.Tooltip("subject", title="Exam")])
    with st.container(border=True):
        st.altair_chart((bars + rules).properties(height=260), width="stretch")
        st.caption("Daily study hours by subject. Red dashed lines mark exam days.")

    horizon = st.segmented_control("Show", ["7 days", "14 days", "Everything"], default="14 days")
    days = {"7 days": 7, "14 days": 14}.get(horizon or "14 days", 10_000)
    end = today + timedelta(days=days - 1)
    shown = [s for s in plan if date.fromisoformat(s["date"]) <= end]
    exams_by_day: dict[str, list[str]] = {}
    for s in subjects:
        if today <= date.fromisoformat(s["exam_date"]) <= end:
            exams_by_day.setdefault(s["exam_date"], []).append(s["name"])
    with st.container(border=True):
        ui.timeline(shown, exams_by_day, color_of, today)

    c1, c2 = st.columns([1, 3])
    if c1.button("Re-optimize now", icon=":material/autorenew:", width="stretch"):
        orch.optimizer.replan(today, "manual request")
        st.rerun()
    with c2.expander("Table view", icon=":material/table_rows:"):
        view = df.assign(day=df["date"].dt.strftime("%a %d %b"))
        st.dataframe(view[["day", "subject", "topic", "hours", "status"]], hide_index=True, width="stretch")


@st.dialog("Add a subject", width="large")
def add_subject_dialog() -> None:
    draft = st.session_state.get("draft")
    if not draft:
        name = st.text_input("Subject", placeholder="e.g. Computer Networks")
        c1, c2 = st.columns(2)
        exam = c1.date_input("Exam date", value=today + timedelta(days=21), min_value=today + timedelta(days=1))
        weakness = c2.slider("How weak are you in it?", 1, 5, 3, help="1 = strong, 5 = weak. Weak subjects get "
                                                                     "more hours and priority.")
        syllabus = st.text_area("Syllabus", height=200, placeholder="Paste units or topics, one per line works best")
        if st.button("Analyze syllabus", icon=":material/document_scanner:", type="primary", width="stretch"):
            if not name.strip() or not syllabus.strip():
                st.error("Enter a subject name and a syllabus.")
            elif name.strip() in exam_by_subject:
                st.error("That subject already exists.")
            else:
                with st.spinner("Syllabus Analyzer is reading…"):
                    topics, note = orch.analyze_syllabus(name.strip(), syllabus, exam)
                st.session_state.draft = {"name": name.strip(), "exam": exam, "weakness": weakness,
                                          "syllabus": syllabus, "topics": topics, "note": note}
                st.rerun(scope="fragment")
        return

    st.markdown(f"**{draft['name']}** · exam {draft['exam']:%d %b} · weakness {draft['weakness']}/5")
    st.caption(draft["note"])
    edited = st.data_editor(
        pd.DataFrame(draft["topics"]), num_rows="dynamic", width="stretch", hide_index=True,
        column_config={
            "name": st.column_config.TextColumn("Topic", required=True, width="large"),
            "est_hours": st.column_config.NumberColumn("Hours", min_value=0.5, max_value=40, step=0.5, format="%.1f"),
            "difficulty": st.column_config.NumberColumn("Difficulty", min_value=1, max_value=5, step=1),
        })
    c1, c2 = st.columns(2)
    if c1.button("Back", icon=":material/arrow_back:", width="stretch"):
        del st.session_state["draft"]
        st.rerun(scope="fragment")
    if c2.button("Add to plan", icon=":material/add_task:", type="primary", width="stretch"):
        rows = [r for r in edited.to_dict("records") if r.get("name") and r.get("est_hours")]
        for r in rows:
            r["difficulty"] = int(r.get("difficulty") or 3)
        orch.add_subject(draft["name"], draft["exam"], draft["weakness"], draft["syllabus"], rows, today)
        del st.session_state["draft"]
        st.rerun()


def page_subjects() -> None:
    head, btn = st.columns([4, 1], vertical_alignment="center")
    with head:
        ui.section("Subjects & syllabus", "menu_book", f"{len(subjects)} subjects")
    if btn.button("Add subject", icon=":material/add:", type="primary", width="stretch"):
        add_subject_dialog()
    if need_subjects():
        return
    stats = {s["subject_id"]: s for s in orch.tracker.subject_stats(today)}
    cols = st.columns(2, gap="medium")
    for i, s in enumerate(subjects):
        color = color_of[s["name"]]
        topics = db.topics(s["id"])
        with cols[i % 2].container(border=True):
            ui.subject_header(s, color, stats[s["id"]]["days_left"], stats[s["id"]]["progress"], topics)
            with st.expander("Manage", icon=":material/tune:"):
                c1, c2 = st.columns(2)
                new_exam = c1.date_input("Exam date", date.fromisoformat(s["exam_date"]), key=f"ex{s['id']}")
                new_weak = c2.slider("Weakness", 1, 5, s["weakness"], key=f"wk{s['id']}")
                if st.button("Save and replan", key=f"sv{s['id']}", icon=":material/save:"):
                    db.update_subject(s["id"], new_exam, new_weak)
                    orch.optimizer.replan(today, f"{s['name']} updated")
                    st.rerun()
                st.caption("Tick topics you've already mastered. The optimizer drops their remaining hours.")
                for t in topics:
                    checked = st.checkbox(f"{t['name']}  ·  {t['est_hours']:g}h · difficulty {t['difficulty']}",
                                          value=bool(t["completed"]), key=f"tp{t['id']}")
                    if checked != bool(t["completed"]):
                        db.set_topic_completed(t["id"], checked)
                        db.log("Progress Tracker", f"Topic '{t['name']}' marked {'mastered' if checked else 'not mastered'}.")
                        orch.optimizer.replan(today, f"topic '{t['name']}' toggled")
                        st.rerun()
                with st.popover("Delete subject", icon=":material/delete:"):
                    st.write(f"Delete **{s['name']}** and all its sessions?")
                    if st.button("Delete", key=f"del{s['id']}", type="primary"):
                        db.delete_subject(s["id"])
                        orch.optimizer.replan(today, f"{s['name']} removed")
                        st.rerun()


def page_progress() -> None:
    ui.section("Progress", "insights")
    if need_subjects():
        return
    stats = orch.tracker.subject_stats(today)
    all_sessions = db.sessions()
    done_n = sum(1 for s in all_sessions if s["status"] == "done")
    missed_n = sum(1 for s in all_sessions if s["status"] == "missed")
    studied = sum(s["studied_hours"] for s in stats)
    remaining = max(0.0, sum(s["target_hours"] - s["studied_hours"] for s in stats))
    past14 = [today - timedelta(days=13 - i) for i in range(14)]
    per_day = [sum(s["actual_hours"] for s in all_sessions if s["status"] == "done" and s["date"] == d.isoformat())
               for d in past14]
    m = st.columns(4)
    m[0].metric("Hours studied", f"{studied:g}", icon=":material/timer:", border=True,
                delta=f"{sum(per_day[-7:]):g}h this week", delta_color="off")
    m[1].metric("Hours remaining", f"{remaining:.1f}", icon=":material/pending_actions:", border=True)
    m[2].metric("Sessions done / missed", f"{done_n} / {missed_n}", icon=":material/fact_check:", border=True)
    m[3].metric("Adherence", f"{done_n / (done_n + missed_n):.0%}" if done_n + missed_n else "–",
                icon=":material/verified:", border=True)
    cols = st.columns(2, gap="medium")
    for i, s in enumerate(stats):
        with cols[i % 2]:
            ui.html(ui.ring_card(s, color_of.get(s["subject"], "#888")))


def page_agents() -> None:
    ui.section("Agents", "hub", "4 planning agents + MCP assistant")
    log = db.recent_log(200)
    last = {}
    for e in log:
        last.setdefault(e["agent"], f"{e['ts'][5:16].replace('T', ' ')} · {e['message'][:70]}")
    ui.agent_cards(last)

    left, right = st.columns([2, 3], gap="large")
    with left:
        ui.section("Coach briefing", "record_voice_over")
        with st.container(border=True):
            if st.button("Generate today's briefing", icon=":material/auto_awesome:", type="primary", width="stretch"):
                with st.spinner("Thinking…"):
                    st.session_state.briefing = orch.coach_briefing(today)
            if "briefing" in st.session_state:
                st.markdown(st.session_state.briefing)
            else:
                st.caption("A short, personalised plan for today based on your progress.")
    with right:
        ui.section("Activity", "timeline", f"{len(log)} events")
        with st.container(border=True, height=520):
            if log:
                ui.feed(log[:60])
            else:
                st.caption("No activity yet.")


nav = st.navigation([
    st.Page(page_today, title="Today", icon=":material/today:", default=True),
    st.Page(page_assistant, title="Assistant", icon=":material/forum:", url_path="assistant"),
    st.Page(page_plan, title="Plan", icon=":material/calendar_month:", url_path="plan"),
    st.Page(page_subjects, title="Subjects", icon=":material/menu_book:", url_path="subjects"),
    st.Page(page_progress, title="Progress", icon=":material/insights:", url_path="progress"),
    st.Page(page_agents, title="Agents", icon=":material/hub:", url_path="agents"),
], position="top")
nav.run()
