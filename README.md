# AI Academic Planner Agent

A multi-agent study planner. Give it your exam dates, syllabus, weekly study hours and weak
subjects, and it builds a day-by-day study plan. When you miss a session it reorganizes the
rest of the schedule automatically.

**Stack:** Python · Streamlit · SQLite · any of several LLM APIs, most with a free tier
(see below). Without a key, offline heuristics are used.

## Agents

| Agent | File | Job |
|---|---|---|
| **Syllabus Analyzer** | `planner/agents/syllabus_analyzer.py` | Turns raw syllabus text into topics with hour estimates and difficulty (LLM with JSON-schema output, or a line-based parser offline). Adds a revision block. |
| **Planner** | `planner/agents/planner.py` | Spreads remaining hours across days. Each block goes to the subject with the most hours still needed per day left, boosted for weak subjects. An earliest-deadline check guarantees a subject gets priority once its slack runs out. Revision is placed in the last days before each exam. |
| **Progress Tracker** | `planner/agents/progress_tracker.py` | Records completed and partial sessions, flags past sessions that were never done as *missed*, and computes progress and adherence. |
| **Study Assistant** | `planner/agents/study_assistant.py` | Chat agent that uses **tool calling**. It is an **MCP client**: it starts the planner's MCP server, discovers its tools, and lets the LLM call them in a loop (up to 8 steps) to answer questions and update the plan. |
| **Schedule Optimizer** | `planner/agents/schedule_optimizer.py` | Rebuilds every future session from what is actually left, and warns when a subject can't fit before its exam. |

`planner/orchestrator.py` connects them. On every app load it runs a cycle: the Tracker
sweeps for missed sessions, and if it finds any, the Optimizer replans. Replanning also runs
when you study more or less than planned, mark a session missed, tick off a topic, change
availability, or add, edit or remove a subject. Every action is written to the **Agents** tab
log. An LLM coach writes a daily briefing from your progress data.

## Tools & MCP

The planner's actions are defined once in `planner/tools.py` and served by an **MCP server**,
`mcp_server.py`, which uses the official `mcp` Python SDK (v2) over stdio:

| Tool | Kind | What it does |
|---|---|---|
| `get_schedule` | read | Sessions for a date range, with ids and status |
| `get_progress` | read | Per-subject progress, adherence, hours that can't fit |
| `list_subjects` | read | Subjects, topics, exam dates, weekly availability |
| `log_study_session` | write | Log the hours actually studied (replans if different from planned) |
| `mark_session_missed` | write | Mark a session missed, then reorganize the schedule |
| `mark_topic_mastered` | write | Drop a topic you already know from the plan |
| `set_availability` | write | Change study hours for a weekday |
| `update_subject` | write | Change an exam date or weakness rating |
| `reoptimize_schedule` | write | Rebuild the remaining plan |

The server also offers a `planner://today` resource and a `daily_briefing` prompt.

```
Streamlit chat ──► Study Assistant (MCP client) ──stdio──► mcp_server.py ──► planner agents ──► SQLite
                        │  tool calls ▲ results
                        ▼
                 LLM (Groq / Gemini / OpenRouter / Ollama / Claude)
```

**Use it from other MCP clients.** Claude Code picks up `.mcp.json` in this folder
automatically. For Claude Desktop, add this to `claude_desktop_config.json`:

```json
{"mcpServers": {"study-planner": {
  "command": "/ABSOLUTE/PATH/.venv/bin/python",
  "args": ["/ABSOLUTE/PATH/mcp_server.py"]}}}
```

Every client shares the same `data/planner.db`, so changes made through MCP show up in the app.
You can debug the server with `npx @modelcontextprotocol/inspector .venv/bin/python mcp_server.py`.

## Run

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python 3.10+
pip install -r requirements.txt
cp .env.example .env    # then paste one free key into .env (optional)
streamlit run app.py
```

## AI models (free options)

Choose the provider in the sidebar under **🧠 AI model**. You can also paste a key there; it
gets saved to `.env`, which is git-ignored. **Auto** uses the first provider that has a key.

| Provider | Key | Default model | Notes |
|---|---|---|---|
| **Groq** (recommended) | `GROQ_API_KEY`, free at [console.groq.com/keys](https://console.groq.com/keys) | `openai/gpt-oss-120b` | Free tier, very fast, strict JSON-schema output |
| **Google Gemini** | `GEMINI_API_KEY`, free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | `gemini-3.8-flash` | Free tier covers Flash / Flash-Lite |
| **OpenRouter** | `OPENROUTER_API_KEY` from [openrouter.ai](https://openrouter.ai/settings/keys) | `openrouter/free` | Routes to whichever `:free` model is available; low daily cap |
| **Ollama** | none | `llama3.2` | Runs locally and offline; `ollama pull llama3.2` |
| **Anthropic** | `ANTHROPIC_API_KEY` | `claude-opus-5-5` | Paid, highest quality |

The model list in the sidebar is editable, so you can type any model ID the provider offers.
Free-tier limits change often; if you hit one, the app falls back to its heuristics and tells
you why.

Click **Load demo** in the sidebar to get three sample subjects. To watch the agentic
behaviour, move the sidebar's **Today** date forward a few days without marking anything
done. The missed sessions are detected and redistributed, and you'll see a toast plus a log
entry.

## Tests

```bash
pip install pytest && python -m pytest -q
```

Data lives in `data/planner.db` (SQLite). Set `PLANNER_DB=/some/other.db` to use a different file
(for example, for experiments).

## UI

Pages: **Today**, **Assistant**, **Plan**, **Subjects**, **Progress** and **Agents**, in a top navigation
bar. The theme is in `.streamlit/config.toml`: Inter and Plus Jakarta Sans fonts, an indigo accent, and
light and dark variants that follow your system. Custom styles are in `ui/styles.py`, and the HTML
components (hero, session cards, week strip, timeline, progress rings, activity feed) are in
`ui/components.py`. Icons are Google Material Symbols.
