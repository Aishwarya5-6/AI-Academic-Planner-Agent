"""Study Assistant agent: a chat agent that manages the plan through tools.

It is an MCP client: each turn it launches the planner's MCP server
(`mcp_server.py`) over stdio, discovers its tools, and runs a tool-calling loop
with the configured LLM (any OpenAI-compatible provider, or Claude)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Awaitable, Callable

import anthropic
import openai
from mcp import Client, StdioServerParameters

from planner import llm

SERVER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "mcp_server.py")
MAX_STEPS = 8

SYSTEM = """You are the Study Assistant inside a student's exam study planner. Today is {today}.
You manage the plan only through the provided tools; never invent sessions, ids or numbers.
- Look things up (get_schedule, get_progress, list_subjects) before answering questions about the plan.
- When the student reports what they studied or skipped, log it with the matching session_id.
- When they say they already know a topic, mark it mastered. When their free time changes, set availability.
- Every change reorganizes the schedule automatically; afterwards, briefly tell them what changed.
Keep replies short, friendly and concrete (dates, hours, topics). Use Markdown lists or tables where helpful. Do not use emojis."""


@dataclass
class ToolCall:
    name: str
    arguments: dict
    result: str
    is_error: bool = False


@dataclass
class AssistantReply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


ToolFn = Callable[[str, dict], Awaitable[ToolCall]]


# --- LLM tool loops -----------------------------------------------------------------
async def _openai_loop(provider: llm.Provider, model: str, system: str, history: list[dict],
                       tools: list, call_tool: ToolFn) -> str:
    client = openai.AsyncOpenAI(api_key=os.environ.get(provider.env_key or "", "") or "ollama",
                                base_url=provider.base_url, timeout=120, max_retries=4)
    specs = [{"type": "function", "function": {"name": t.name, "description": t.description or "",
                                               "parameters": t.input_schema}} for t in tools]
    messages = [{"role": "system", "content": system}, *history]
    for _ in range(MAX_STEPS):
        resp = await client.chat.completions.create(model=model, messages=messages, tools=specs,
                                                    tool_choice="auto", max_tokens=4000)
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return msg.content or ""
        # model_dump keeps provider extras on tool calls (e.g. Gemini thought signatures).
        messages.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [tc.model_dump(exclude_none=True) for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = None
            if not isinstance(args, dict):
                content = "ERROR: arguments were not a valid JSON object; retry with valid JSON."
            else:
                call = await call_tool(tc.function.name, args)
                content = ("ERROR: " if call.is_error else "") + call.result
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
    return "I stopped after several tool steps. Could you rephrase or narrow the request?"


async def _anthropic_loop(model: str, system: str, history: list[dict], tools: list, call_tool: ToolFn) -> str:
    client = anthropic.AsyncAnthropic()
    specs = [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
             for t in tools]
    messages = list(history)
    for _ in range(MAX_STEPS):
        resp = await client.beta.messages.create(
            model=model, max_tokens=16000, system=system, tools=specs, messages=messages,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            return "Sorry, I can't help with that request."
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for block in resp.content:
            if block.type == "tool_use":
                call = await call_tool(block.name, block.input)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": call.result,
                                "is_error": call.is_error})
        messages.append({"role": "user", "content": results})
    return "I stopped after several tool steps. Could you rephrase or narrow the request?"


# --- MCP client ----------------------------------------------------------------------
async def _chat(history: list[dict], today: date, db_path: str | None) -> AssistantReply:
    selected = llm.active()
    if selected is None:
        raise llm.LLMUnavailable("No AI provider configured. Add a free API key in the sidebar.")
    provider_name, model = selected
    provider = llm.PROVIDERS[provider_name]

    env = {**os.environ, "PLANNER_TODAY": today.isoformat()}
    if db_path:
        env["PLANNER_DB"] = db_path
    server = StdioServerParameters(command=sys.executable, args=[SERVER_PATH], env=env)
    trace: list[ToolCall] = []

    async with Client(server) as client:
        tools = (await client.list_tools()).tools

        async def call_tool(name: str, args: dict) -> ToolCall:
            try:
                result = await client.call_tool(name, args)
                text = "\n".join(getattr(b, "text", "") for b in result.content)
                call = ToolCall(name, args, text, bool(result.is_error))
            except Exception as e:  # protocol-level failure: report it to the model, keep going
                call = ToolCall(name, args, f"{type(e).__name__}: {e}", True)
            trace.append(call)
            return call

        system = SYSTEM.format(today=today.strftime("%A %d %B %Y"))
        if provider.base_url is None:
            text = await _anthropic_loop(model, system, history, tools, call_tool)
        else:
            text = await _openai_loop(provider, model, system, history, tools, call_tool)
    return AssistantReply(text, trace)


def chat(history: list[dict], today: date, db_path: str | None = None) -> AssistantReply:
    """Run one assistant turn. `history` is [{"role": "user"|"assistant", "content": str}, ...]."""
    try:
        try:
            return asyncio.run(_chat(history, today, db_path))
        except BaseExceptionGroup as group:  # the MCP client's task group wraps errors
            raise _first_leaf(group) from group
    except (openai.AuthenticationError, anthropic.AuthenticationError) as e:
        raise llm.LLMUnavailable("Invalid API key for the selected provider") from e
    except (openai.RateLimitError, anthropic.RateLimitError) as e:
        raise llm.LLMUnavailable("Free-tier rate limit hit, try again in a minute") from e
    except openai.BadRequestError as e:
        raise llm.LLMUnavailable(f"The model rejected the request (does it support tool calling?): {e}") from e
    except (openai.APIError, anthropic.APIError) as e:
        raise llm.LLMUnavailable(f"API error: {e}") from e


def _first_leaf(group: BaseExceptionGroup) -> BaseException:
    exc: BaseException = group
    while isinstance(exc, BaseExceptionGroup):
        exc = exc.exceptions[0]
    return exc
