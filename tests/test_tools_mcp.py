import asyncio
import json
from datetime import date, timedelta

import pytest
from mcp import Client
from openai.types.chat import ChatCompletion

import mcp_server
from planner import llm
from planner.agents import study_assistant
from planner.db import Database
from planner.orchestrator import Orchestrator
from planner.sample_data import load_sample
from planner.tools import PlannerTools, ToolError

TODAY = date(2026, 10, 12)


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "planner.db")
    load_sample(Orchestrator(Database(path)), TODAY)
    monkeypatch.setenv("PLANNER_DB", path)
    monkeypatch.setenv("PLANNER_TODAY", TODAY.isoformat())
    return path


def test_tools_change_the_plan(db_path):
    tools = PlannerTools(Database(db_path), TODAY)
    today = tools.get_schedule(days=1)["sessions"]
    assert today
    tools.mark_session_missed(today[0]["session_id"])
    assert tools.get_schedule(days=1)["sessions"][0]["status"] == "missed"

    tools.set_availability("saturday", 8)
    assert tools.list_subjects()["availability_hours"]["saturday"] == 8

    tools.mark_topic_mastered("linear", "determinants")
    lin = next(s for s in tools.list_subjects()["subjects"] if s["subject"] == "Linear Algebra")
    assert next(t for t in lin["topics"] if t["topic"] == "Determinants")["completed"]

    with pytest.raises(ToolError):
        tools.mark_session_missed(99999)
    with pytest.raises(ToolError):
        tools.set_availability("funday", 2)


def test_mcp_server_exposes_tools(db_path):
    async def run():
        async with Client(mcp_server.build_server()) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            progress = await client.call_tool("get_progress", {})
            bad = await client.call_tool("mark_session_missed", {"session_id": 99999})
            return names, progress, bad

    names, progress, bad = asyncio.run(run())
    assert {"get_schedule", "get_progress", "log_study_session", "mark_session_missed",
            "mark_topic_mastered", "set_availability", "update_subject"} <= names
    assert len(json.loads(progress.content[0].text)["subjects"]) == 3
    assert bad.is_error and "No session with id 99999" in bad.content[0].text


def _completion(message: dict) -> ChatCompletion:
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 0, "model": "fake",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", **message}}]})


class FakeLLM:
    """Scripted model: look up today's schedule, mark the first session missed, then answer."""

    def __init__(self, *args, **kwargs):
        self.chat = self
        self.completions = self

    async def create(self, model, messages, tools, **kwargs):
        assert {t["function"]["name"] for t in tools} >= {"get_schedule", "mark_session_missed"}
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        if not tool_msgs:
            return _completion({"content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "get_schedule", "arguments": json.dumps({"days": 1})}}]})
        if len(tool_msgs) == 1:
            first = json.loads(tool_msgs[0]["content"])["sessions"][0]["session_id"]
            return _completion({"content": None, "tool_calls": [{"id": "c2", "type": "function", "function": {
                "name": "mark_session_missed", "arguments": json.dumps({"session_id": first})}}]})
        return _completion({"content": "Done, I moved it to later days."})


def test_assistant_uses_mcp_tools_end_to_end(db_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake")
    monkeypatch.setattr(study_assistant.openai, "AsyncOpenAI", FakeLLM)
    llm.configure({"llm_provider": "groq"})

    reply = study_assistant.chat([{"role": "user", "content": "I skipped my first session today"}], TODAY,
                                 db_path)

    assert reply.text == "Done, I moved it to later days."
    assert [c.name for c in reply.tool_calls] == ["get_schedule", "mark_session_missed"]
    assert not any(c.is_error for c in reply.tool_calls)
    db = Database(db_path)
    assert db.sessions(TODAY, TODAY)[0]["status"] == "missed"
    assert any(e["agent"] == "Schedule Optimizer" and "missed" in e["message"] for e in db.recent_log())
