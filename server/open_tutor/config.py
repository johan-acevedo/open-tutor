"""Runtime configuration from the environment.

Credentials only ever come from the backend environment (for Johan's instance:
Infisical `homelab` plus a private env file, see server/README.md). Nothing here
is sent to the browser except the LiveKit URL and a short-lived room token.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# One worker per LiveKit project registers under this name. A test worker can use another
# name (with a web service set the same way) so it never takes a family session.
AGENT_NAME = os.environ.get("TUTOR_AGENT_NAME", "open-tutor")

# Tutor model routes. There is no silent fallback: the route is chosen by TUTOR_LLM.
#
# "go" (default) is Muse Spark 1.3 Contributor on Johan's OpenCode Go subscription. Go
# serves that model only on its OpenAI Responses endpoint, over HTTP streaming (the
# Responses WebSocket returns 404 there), with function calls as structured
# `function_call` output items. Minimal reasoning: in tests it called the board tool as
# reliably as "low" (24/24) with a median of 1.4 s to first output instead of 4.2 s.
#
# "gemini-dev" is the earlier development route (Gemini 3.5 Flash Lite through Google's
# OpenAI-compatible Chat Completions). It is kept only to reproduce the board/voice bug
# it caused: it often writes board content into its spoken reply instead of calling a
# board tool. Do not deploy it.
LLM_ROUTES = {
    "go": {
        "api": "responses",
        "base_url": "https://opencode.ai/inference/go/openai/v1",
        "model": "muse-spark-1.3-contributor",
        "key": "OPENCODE_GO_API_KEY",
        "reasoning_effort": "minimal",
    },
    "gemini-dev": {
        "api": "chat",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-3.5-flash-lite",
        "key": "GEMINI_API_KEY",
        "reasoning_effort": None,
    },
}

# Go asks clients to name themselves rather than send a generic SDK user agent.
USER_AGENT = "open-tutor/0.1 (+https://github.com/johan-acevedo/open-tutor)"


@dataclass(frozen=True)
class LLMRoute:
    name: str
    api: str
    base_url: str
    model: str
    api_key: str
    reasoning_effort: str | None


def llm_route(environ: dict[str, str] | None = None) -> LLMRoute:
    env = os.environ if environ is None else environ
    name = env.get("TUTOR_LLM", "go")
    if name not in LLM_ROUTES:
        raise ValueError(f"TUTOR_LLM must be one of {', '.join(LLM_ROUTES)}")
    spec = LLM_ROUTES[name]
    key = env.get(spec["key"], "")
    if not key:
        raise ValueError(f"TUTOR_LLM={name} needs {spec['key']} in the backend environment")
    return LLMRoute(
        name=name,
        api=spec["api"],
        base_url=env.get("TUTOR_LLM_BASE_URL", spec["base_url"]),
        model=env.get("TUTOR_LLM_MODEL", spec["model"]),
        api_key=key,
        reasoning_effort=env.get("TUTOR_LLM_REASONING", spec["reasoning_effort"]) or None,
    )


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default
