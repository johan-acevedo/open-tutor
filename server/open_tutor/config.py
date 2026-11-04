"""Runtime configuration from the environment.

Credentials only ever come from the backend environment (for Johan's instance:
Infisical `homelab` plus a private env file, see server/README.md). Nothing here
is sent to the browser except the LiveKit URL and a short-lived room token.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

AGENT_NAME = "open-tutor"

# Tutor model routes, all OpenAI-compatible chat completions with streaming,
# tools and image input. "spark" is the intended teaching model through an
# ordinary metered API (not the Contributor/coding-agent route). "gemini-dev"
# exists only to exercise the pipeline with fictional material while the
# Spark route has no credit; it is never selected silently.
LLM_ROUTES = {
    "spark": {
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta/muse-spark-1.3",
        "key": "OPENROUTER_API_KEY",
        "reasoning_effort": "low",
    },
    "gemini-dev": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-3.5-flash-lite",
        "key": "GEMINI_API_KEY",
        "reasoning_effort": None,
    },
}


@dataclass(frozen=True)
class LLMRoute:
    name: str
    base_url: str
    model: str
    api_key: str
    reasoning_effort: str | None


def llm_route(environ: dict[str, str] | None = None) -> LLMRoute:
    env = os.environ if environ is None else environ
    name = env.get("TUTOR_LLM", "spark")
    if name not in LLM_ROUTES:
        raise ValueError(f"TUTOR_LLM must be one of {', '.join(LLM_ROUTES)}")
    spec = LLM_ROUTES[name]
    key = env.get(spec["key"], "")
    if not key:
        raise ValueError(f"TUTOR_LLM={name} needs {spec['key']} in the backend environment")
    return LLMRoute(
        name=name,
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
