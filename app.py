"""AI Academic Planner: Streamlit front end.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from planner import llm
from planner.agents import study_assistant
from planner.db import Database
from planner.orchestrator import Orchestrator
from planner.sample_data import load_sample

st.set_page_config(page_title="AI Academic Planner", page_icon="📚", layout="wide")

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
# Validated categorical palette, assigned to subjects in a fixed order by subject id.
SUBJECT_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]


@st.cache_resource
def get_db() -> Database:
    return Database()


db = get_db()
orch = Orchestrator(db)
settings = db.get_settings()

# --- sidebar: availability & settings -------------------------------------
with st.sidebar:
    st.title("📚 AI Academic Planner")
    today = st.date_input("Today", value=date.today(),
                          help="Move this forward to simulate days passing and watch the agents react.")

    with st.expander("⏰ Weekly availability", expanded=not db.subjects()):
        new_hours = {}
        for i, d in enumerate(WEEKDAYS):
            new_hours[str(i)] = st.slider(d, 0.0, 12.0, float(settings["weekday_hours"][str(i)]), 0.5,
                                          key=f"wh{i}")
        session_length = st.select_slider("Session length (h)", [0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
                                          value=float(settings["session_length"]))
        revision_pct = st.slider("Revision buffer (% of hours, new subjects)", 0, 40,
                                 int(settings["revision_pct"]), 5)
        if st.button("Save & replan", width="stretch"):
            settings.update(weekday_hours=new_hours, session_length=session_length, revision_pct=revision_pct)
            db.save_settings(settings)
            orch.optimizer.replan(today, "availability changed")
            st.rerun()

    use_llm = st.toggle("Use AI for analysis & coaching", value=bool(settings["use_llm"]))
    if use_llm != settings["use_llm"]:
        settings["use_llm"] = use_llm
        db.save_settings(settings)
    llm.configure(settings)
    if use_llm:
        with st.expander("🧠 AI model", expanded=not llm.is_configured()):
            options = ["auto"] + list(llm.PROVIDERS)
            provider = st.selectbox(
                "Provider", options, index=options.index(settings.get("llm_provider", "auto")),
                format_func=lambda p: "Auto (first free provider with a key)" if p == "auto"
                else llm.PROVIDERS[p].label)
            if provider != settings.get("llm_provider"):
                settings["llm_provider"] = provider
                db.save_settings(settings)
                st.rerun()
            if provider != "auto":
                prov = llm.PROVIDERS[provider]
                models = settings.get("llm_models", {})
                current = models.get(provider) or prov.default_model
                model = st.selectbox("Model", prov.models + ([current] if current not in prov.models else []),
                                     index=(prov.models + [current]).index(current), accept_new_options=True)
                if model != current:
                    settings["llm_models"] = {**models, provider: model}
                    db.save_settings(settings)
                    st.rerun()
                if prov.env_key:
                    status = "✅ key set" if llm.has_key(provider) else "no key yet"
                    st.caption(f"`{prov.env_key}`: {status}. [Get a free key]({prov.signup_url})"
                               if prov.free else f"`{prov.env_key}`: {status}. [Get a key]({prov.signup_url})")
                    key = st.text_input("API key", type="password", key=f"key_{provider}",
                                        placeholder="Paste key, saved to .env")
                    if st.button("Save key", disabled=not key, width="stretch"):
                        llm.save_key(provider, key)
                        st.rerun()
                else:
                    st.caption(f"Runs locally. [Install Ollama]({prov.signup_url}), then "
                               f"`ollama pull {current}`.")
        if llm.is_configured():
            st.caption(f"✅ Using **{llm.describe()}**")
        else:
            st.caption("⚠️ No API key yet, so offline heuristics are used. Pick a provider above and add a "
                       "free key.")

    st.divider()
    c1, c2 = st.columns(2)
    if c1.button("Load demo", width="stretch"):
        load_sample(orch, today)
        st.rerun()
    if c2.button("Reset all", width="stretch"):
        db.reset()
        st.rerun()

# --- autonomous cycle: detect misses & reorganize ---------------------------
missed = orch.run_cycle(today)
if missed:
    st.toast(f"🔁 {len(missed)} missed session(s) detected. Your schedule has been reorganized.")

subjects = db.subjects()
color_of = {s["name"]: SUBJECT_COLORS[i % len(SUBJECT_COLORS)]
            for i, s in enumerate(sorted(subjects, key=lambda s: s["id"]))}

tab_today, tab_chat, tab_plan, tab_subjects, tab_progress, tab_agents = st.tabs(
    ["📅 Today", "💬 Assistant", "🗓️ Study plan", "📚 Subjects & syllabus", "📈 Progress", "🤖 Agents"])


def subject_dot(name: str) -> str:
    return f"<span style='color:{color_of.get(name, '#888')}'>●</span>"


# --- Today -----------------------------------------------------------------
with tab_today:
    st.header(today.strftime("%A, %d %B %Y"))
    if not subjects:
        st.info("Add a subject in **Subjects & syllabus**, or click **Load demo** in the sidebar.")
    todays = db.sessions(today, today)
    if subjects and not todays:
        st.success("Nothing scheduled today. 🎉")
    for s in todays:
        with st.container(border=True):
            left, right = st.columns([3, 2])
            left.markdown(f"{subject_dot(s['subject'])} **{s['subject']}** · {s['topic']}  \n"
                          f"Planned: **{s['hours']:g}h**", unsafe_allow_html=True)
            if s["status"] == "planned":
                actual = right.number_input("Hours studied", 0.0, 12.0, float(s["hours"]), 0.25,
                                            key=f"act{s['id']}", label_visibility="collapsed")
                b1, b2 = right.columns(2)
                if b1.button("✅ Done", key=f"done{s['id']}", width="stretch"):
                    if actual > 0:
                        orch.complete_session(s, actual, today)
                    else:
                        orch.miss_session(s, today)
                    st.rerun()
                if b2.button("❌ Missed", key=f"miss{s['id']}", width="stretch"):
                    orch.miss_session(s, today)
                    st.rerun()
            else:
                icon = "✅" if s["status"] == "done" else "❌"
                right.markdown(f"{icon} {s['status'].title()}"
                               + (f" · {s['actual_hours']:g}h" if s["status"] == "done" else ""))

    upcoming = db.sessions(today + timedelta(days=1), today + timedelta(days=7), "planned")
    if upcoming:
        st.subheader("Next 7 days")
        df = pd.DataFrame(upcoming)
        df["day"] = pd.to_datetime(df["date"]).dt.strftime("%a %d %b")
        st.dataframe(df[["day", "subject", "topic", "hours"]], hide_index=True, width="stretch")

# --- Study plan ------------------------------------------------------------
with tab_plan:
    shortfall = orch.optimizer.feasibility(today) if subjects else {}
    names = {s["id"]: s["name"] for s in subjects}
    for sid, h in shortfall.items():
        st.warning(f"**{names[sid]}**: {h:g}h of work won't fit before the exam. Add study hours, "
                   f"lower the weakness rating, or tick off topics you already know.")

    plan = db.sessions(today)
    if not plan:
        st.info("No upcoming sessions yet.")
    else:
        df = pd.DataFrame(plan)
        df["date"] = pd.to_datetime(df["date"])
        daily = df.groupby(["date", "subject"], as_index=False)["hours"].sum()
        exams = pd.DataFrame([{"date": pd.to_datetime(s["exam_date"]), "subject": s["name"]}
                              for s in subjects if date.fromisoformat(s["exam_date"]) >= today])
        domain = list(color_of)
        bars = alt.Chart(daily).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, stroke="white",
                                         strokeWidth=1).encode(
            x=alt.X("yearmonthdate(date):T", title=None),
            y=alt.Y("sum(hours):Q", title="Hours"),
            color=alt.Color("subject:N", scale=alt.Scale(domain=domain, range=[color_of[n] for n in domain]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=[alt.Tooltip("yearmonthdate(date):T", title="Day"), "subject", "hours"],
        )
        rules = alt.Chart(exams).mark_rule(strokeDash=[4, 3], color="gray").encode(
            x="yearmonthdate(date):T", tooltip=[alt.Tooltip("subject", title="Exam")])
        st.altair_chart((bars + rules).properties(height=280), width="stretch")
        st.caption("Dashed lines mark exam days.")

        view = df.copy()
        view["day"] = view["date"].dt.strftime("%a %d %b")
        view["status"] = view["status"].map({"planned": "🕒 planned", "done": "✅ done", "missed": "❌ missed"})
        st.dataframe(view[["day", "subject", "topic", "hours", "status"]], hide_index=True,
                     width="stretch", height=420)

    if st.button("🔁 Re-optimize now"):
        orch.optimizer.replan(today, "manual request")
        st.rerun()

# --- Subjects & syllabus -----------------------------------------------------
with tab_subjects:
    st.subheader("Add a subject")
    with st.form("analyze"):
        c1, c2, c3 = st.columns([2, 1, 1])
        name = c1.text_input("Subject", placeholder="e.g. Linear Algebra")
        exam = c2.date_input("Exam date", value=today + timedelta(days=21), min_value=today + timedelta(days=1))
        weakness = c3.slider("How weak are you? (1 = strong, 5 = weak)", 1, 5, 3)
        syllabus = st.text_area("Syllabus (paste units/topics, one per line works best)", height=180)
        go = st.form_submit_button("🔍 Analyze syllabus")
    if go:
        if not name.strip() or not syllabus.strip():
            st.error("Enter both a subject name and a syllabus.")
        elif name.strip() in {s["name"] for s in subjects}:
            st.error("That subject already exists.")
        else:
            with st.spinner("Syllabus Analyzer is reading the syllabus…"):
                topics, note = orch.analyze_syllabus(name.strip(), syllabus, exam)
            st.session_state.draft = {"name": name.strip(), "exam": exam, "weakness": weakness,
                                      "syllabus": syllabus, "topics": topics, "note": note}

    draft = st.session_state.get("draft")
    if draft:
        st.markdown(f"**Review topics for {draft['name']}.** {draft['note']}")
        edited = st.data_editor(
            pd.DataFrame(draft["topics"]), num_rows="dynamic", width="stretch", hide_index=True,
            column_config={
                "name": st.column_config.TextColumn("Topic", required=True),
                "est_hours": st.column_config.NumberColumn("Est. hours", min_value=0.5, max_value=40, step=0.5),
                "difficulty": st.column_config.NumberColumn("Difficulty (1-5)", min_value=1, max_value=5, step=1),
            }, key="topic_editor")
        b1, b2 = st.columns([1, 5])
        if b1.button("✅ Add to plan", type="primary"):
            rows = [r for r in edited.to_dict("records") if r.get("name") and r.get("est_hours")]
            for r in rows:
                r["difficulty"] = int(r.get("difficulty") or 3)
            orch.add_subject(draft["name"], draft["exam"], draft["weakness"], draft["syllabus"], rows, today)
            del st.session_state["draft"]
            st.rerun()
        if b2.button("Discard"):
            del st.session_state["draft"]
            st.rerun()

    if subjects:
        st.subheader("Your subjects")
    done_hours = db.done_hours_by_topic()
    for s in subjects:
        exam_d = date.fromisoformat(s["exam_date"])
        days_left = (exam_d - today).days
        label = f"{s['name']}: exam {exam_d:%d %b} ({days_left} days left)" if days_left >= 0 \
            else f"{s['name']}: exam was {exam_d:%d %b}"
        with st.expander(label):
            c1, c2, c3 = st.columns([1, 1, 1])
            new_exam = c1.date_input("Exam date", exam_d, key=f"ex{s['id']}")
            new_weak = c2.slider("Weakness", 1, 5, s["weakness"], key=f"wk{s['id']}")
            if c3.button("Save & replan", key=f"sv{s['id']}"):
                db.update_subject(s["id"], new_exam, new_weak)
                orch.optimizer.replan(today, f"{s['name']} updated")
                st.rerun()
            st.caption("Tick topics you've already mastered. The optimizer will drop them from the plan.")
            for t in db.topics(s["id"]):
                c1, c2 = st.columns([5, 2])
                checked = c1.checkbox(f"{t['name']}", value=bool(t["completed"]), key=f"tp{t['id']}")
                c2.caption(f"{done_hours.get(t['id'], 0):g}/{t['est_hours']:g}h · diff {t['difficulty']}")
                if checked != bool(t["completed"]):
                    db.set_topic_completed(t["id"], checked)
                    db.log("Progress Tracker", f"Topic '{t['name']}' marked "
                                               f"{'complete' if checked else 'incomplete'}.")
                    orch.optimizer.replan(today, f"topic '{t['name']}' toggled")
                    st.rerun()
            if st.button("🗑️ Delete subject", key=f"del{s['id']}"):
                db.delete_subject(s["id"])
                orch.optimizer.replan(today, f"{s['name']} removed")
                st.rerun()

# --- Progress ----------------------------------------------------------------
with tab_progress:
    stats = orch.tracker.subject_stats(today)
    if not stats:
        st.info("No subjects yet.")
    else:
        all_sessions = db.sessions()
        done_n = sum(1 for s in all_sessions if s["status"] == "done")
        missed_n = sum(1 for s in all_sessions if s["status"] == "missed")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Hours studied", f"{sum(s['studied_hours'] for s in stats):g}")
        m2.metric("Hours remaining", f"{max(0, sum(s['target_hours'] - s['studied_hours'] for s in stats)):.1f}")
        m3.metric("Sessions done / missed", f"{done_n} / {missed_n}")
        m4.metric("Adherence", f"{done_n / (done_n + missed_n):.0%}" if done_n + missed_n else "–")
        for s in stats:
            with st.container(border=True):
                st.markdown(f"{subject_dot(s['subject'])} **{s['subject']}**: exam in {s['days_left']} days · "
                            f"weakness {s['weakness']}/5", unsafe_allow_html=True)
                st.progress(min(1.0, s["progress"]),
                            text=f"{s['progress']:.0%} · {s['studied_hours']:g} of {s['target_hours']:g}h · "
                                 f"{s['topics_done']}/{s['topics_total']} topics ticked off")
                if s["missed_sessions"]:
                    st.caption(f"❌ {s['missed_sessions']} missed session(s), {s['missed_hours']:g}h "
                               f"rescheduled automatically")

# --- Assistant (LLM + MCP tools) -------------------------------------------------
with tab_chat:
    st.caption("Chat with the Study Assistant. It reads and changes your plan through the planner's "
               "**MCP server** tools, e.g. *“I skipped today's DSA session”*, *“I already know determinants”*, "
               "*“I can do 6 hours on Saturdays now”*, *“Am I on track for Linear Algebra?”*")
    chat_log = st.session_state.setdefault("chat", [])
    for m in chat_log:
        with st.chat_message(m["role"]):
            if m.get("tools"):
                with st.expander(f"🔧 Used {len(m['tools'])} tool call(s)"):
                    for c in m["tools"]:
                        st.markdown(f"{'❌' if c.is_error else '✅'} `{c.name}({json.dumps(c.arguments)})`")
                        st.code(c.result[:1500], language="json")
            st.markdown(m["content"])
    if not use_llm or not llm.is_configured():
        st.info("The assistant needs an AI provider. Turn on **Use AI** and add a free key in the sidebar.")
    elif prompt := st.chat_input("Ask or tell the assistant something…"):
        chat_log.append({"role": "user", "content": prompt})
        history = [{"role": m["role"], "content": m["content"]} for m in chat_log[-12:]]
        with st.spinner("Assistant is working…"):
            try:
                reply = study_assistant.chat(history, today, db.path)
                chat_log.append({"role": "assistant", "content": reply.text or "(no reply)",
                                 "tools": reply.tool_calls})
            except llm.LLMUnavailable as e:
                chat_log.append({"role": "assistant", "content": f"⚠️ {e}"})
        st.rerun()
    if chat_log and st.button("Clear chat"):
        st.session_state.chat = []
        st.rerun()

# --- Agents --------------------------------------------------------------------
with tab_agents:
    st.subheader("🧑‍🏫 Coach briefing")
    if st.button("Generate today's briefing"):
        with st.spinner("Thinking…"):
            st.session_state.briefing = orch.coach_briefing(today)
    if "briefing" in st.session_state:
        st.markdown(st.session_state.briefing)

    st.subheader("Agent activity")
    log = db.recent_log()
    if log:
        st.dataframe(pd.DataFrame(log)[["ts", "agent", "message"]], hide_index=True, width="stretch",
                     column_config={"message": st.column_config.TextColumn(width="large")})
    else:
        st.caption("No activity yet.")
