"""Provider-agnostic LLM access. Free-tier providers (Groq, Google Gemini,
OpenRouter) and local Ollama all speak the OpenAI-compatible API, so a single
`openai` client covers them; Anthropic (paid) goes through its own SDK.

Every caller must handle `LLMUnavailable` so the app keeps working with
heuristics when no key is configured or a free quota runs out."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

import anthropic
import openai

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")


@dataclass(frozen=True)
class Provider:
    label: str
    env_key: str | None  # None => no key needed (local)
    default_model: str
    models: list[str] = field(default_factory=list)
    base_url: str | None = None  # None => Anthropic SDK
    signup_url: str = ""
    free: bool = True


PROVIDERS: dict[str, Provider] = {
    "groq": Provider(
        "Groq (free tier, very fast)", "GROQ_API_KEY", "openai/gpt-oss-120b",
        ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"],
        "https://api.groq.com/openai/v1", "https://console.groq.com/keys"),
    "gemini": Provider(
        "Google Gemini (free tier)", "GEMINI_API_KEY", "gemini-3.8-flash",
        ["gemini-3.8-flash", "gemini-3.5-flash-lite"],
        "https://generativelanguage.googleapis.com/v1beta/openai/", "https://aistudio.google.com/apikey"),
    "openrouter": Provider(
        "OpenRouter (free models)", "OPENROUTER_API_KEY", "openrouter/free",
        ["openrouter/free", "nvidia/nemotron-3-super-120b-a12b:free", "google/gemma-4-31b-it:free"],
        "https://openrouter.ai/api/v1", "https://openrouter.ai/settings/keys"),
    "ollama": Provider(
        "Ollama (local, offline)", None, "llama3.2", ["llama3.2", "qwen3", "gemma3"],
        os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"), "https://ollama.com/download"),
    "anthropic": Provider(
        "Anthropic Claude (paid)", "ANTHROPIC_API_KEY", "claude-opus-5-5",
        ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"],
        None, "https://platform.claude.com/settings/keys", free=False),
}
# Order tried when the provider is "auto". Ollama is never auto-picked (it may not be running).
AUTO_ORDER = ["groq", "gemini", "openrouter", "anthropic"]


class LLMUnavailable(Exception):
    pass


# --- .env handling ------------------------------------------------------------
def _load_dotenv() -> None:
    if not os.path.exists(ENV_PATH):
        return
    with open(ENV_PATH) as f:
        for line in f:
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                v = re.split(r"\s+#", v, maxsplit=1)[0].strip().strip("'\"")  # drop inline comments
                if v:
                    os.environ.setdefault(k.strip(), v)


def save_key(provider: str, key: str) -> None:
    """Persist an API key to the project's .env (git-ignored) and the running process."""
    env_key = PROVIDERS[provider].env_key
    if not env_key:
        return
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH) as f:
            lines = [ln for ln in f.read().splitlines() if not ln.startswith(f"{env_key}=")]
    lines.append(f"{env_key}={key.strip()}")
    with open(ENV_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(ENV_PATH, 0o600)
    os.environ[env_key] = key.strip()


_load_dotenv()

# --- active selection -----------------------------------------------------------
_selected = {"provider": "auto", "models": {}}


def configure(settings: dict) -> None:
    _selected["provider"] = settings.get("llm_provider", "auto")
    _selected["models"] = settings.get("llm_models", {})


def has_key(provider: str) -> bool:
    env_key = PROVIDERS[provider].env_key
    return env_key is None or bool(os.environ.get(env_key))


def active() -> tuple[str, str] | None:
    """(provider, model) that will be used, or None if nothing is configured."""
    choice = _selected["provider"]
    candidates = AUTO_ORDER if choice == "auto" else [choice]
    for p in candidates:
        if p in PROVIDERS and has_key(p):
            return p, _selected["models"].get(p) or PROVIDERS[p].default_model
    return None


def is_configured() -> bool:
    return active() is not None


def describe() -> str:
    a = active()
    return f"{PROVIDERS[a[0]].label.split(' (')[0]} · {a[1]}" if a else "offline heuristics"


# --- calls ---------------------------------------------------------------------------
def _extract_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise LLMUnavailable("Model did not return JSON")
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as e:
            raise LLMUnavailable("Model returned malformed JSON") from e


def _openai_call(provider: Provider, model: str, system: str, prompt: str, schema: dict | None) -> str:
    client = openai.OpenAI(api_key=os.environ.get(provider.env_key or "", "") or "ollama",
                           base_url=provider.base_url, timeout=120, max_retries=4)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    if schema is None:
        formats = [None]
    else:
        # Prefer strict schema decoding; fall back to plain JSON mode for models that lack it.
        schema_hint = f"\n\nRespond with only a JSON object matching this schema:\n{json.dumps(schema)}"
        messages[0]["content"] += schema_hint
        formats = [{"type": "json_schema", "json_schema": {"name": "result", "schema": schema, "strict": True}},
                   {"type": "json_object"}, None]
    last_error: Exception | None = None
    for fmt in formats:
        try:
            kwargs = {"response_format": fmt} if fmt else {}
            resp = client.chat.completions.create(model=model, messages=messages, max_tokens=8000, **kwargs)
            text = resp.choices[0].message.content or ""
            if text.strip():
                return text
            last_error = LLMUnavailable("Empty response")
        except openai.BadRequestError as e:  # unsupported response_format -> try the next one
            if "api key" in str(e).lower():  # Gemini reports bad keys as 400
                raise LLMUnavailable(f"Invalid {provider.env_key}") from e
            last_error = e
        except openai.AuthenticationError as e:
            raise LLMUnavailable(f"Invalid {provider.env_key}") from e
        except openai.RateLimitError as e:
            raise LLMUnavailable("Free-tier rate limit hit, try again in a minute") from e
        except openai.NotFoundError as e:
            raise LLMUnavailable(f"Model '{model}' not found on this provider") from e
        except openai.APIStatusError as e:
            raise LLMUnavailable(f"API error {e.status_code}") from e
        except openai.APIConnectionError as e:
            raise LLMUnavailable(f"Could not reach {provider.label}") from e
    raise LLMUnavailable(f"Request failed: {last_error}")


def _anthropic_call(model: str, system: str, prompt: str, schema: dict | None) -> str:
    output_config: dict = {"effort": "medium" if schema else "low"}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    try:
        response = anthropic.Anthropic().beta.messages.create(
            model=model, max_tokens=16000, system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config=output_config,
            # Server-side refusal fallback: a declined request is retried on a suitable model.
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise LLMUnavailable("Invalid ANTHROPIC_API_KEY") from e
    except anthropic.RateLimitError as e:
        raise LLMUnavailable("Rate limited by the API, try again shortly") from e
    except anthropic.APIStatusError as e:
        raise LLMUnavailable(f"API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMUnavailable("Could not reach the Claude API") from e
    if response.stop_reason in ("refusal", "max_tokens"):
        raise LLMUnavailable(f"Request stopped ({response.stop_reason})")
    return "".join(b.text for b in response.content if b.type == "text")


def _call(system: str, prompt: str, schema: dict | None) -> str:
    a = active()
    if a is None:
        raise LLMUnavailable("No API key configured")
    name, model = a
    provider = PROVIDERS[name]
    if provider.base_url is None:
        return _anthropic_call(model, system, prompt, schema)
    return _openai_call(provider, model, system, prompt, schema)


def complete_json(system: str, prompt: str, schema: dict) -> dict:
    return _extract_json(_call(system, prompt, schema))


def complete_text(system: str, prompt: str) -> str:
    return _call(system, prompt, None)
