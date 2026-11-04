"""The tutor model for one session, per the route in config.LLM_ROUTES."""

from __future__ import annotations

import logging
from typing import Any

from livekit.agents import llm
from livekit.plugins import openai
from livekit.plugins.openai.responses import llm as responses
from openai import AsyncOpenAI
from openai.types import Reasoning

from .config import USER_AGENT, llm_route

log = logging.getLogger("open-tutor")


class _GoResponsesStream(responses.LLMStream):
    """OpenCode Go reports `input_tokens_details.cache_write_tokens: null`.

    LiveKit's usage record requires an integer there, so without this the stream raised
    a connection error at `response.completed`, after the reply and its tool calls had
    already streamed, and the turn failed.
    """

    def _handle_response_completed(self, event) -> llm.ChatChunk | None:
        usage = event.response.usage
        if usage is not None:
            details = usage.input_tokens_details
            if details is not None and getattr(details, "cache_write_tokens", 0) is None:
                details.cache_write_tokens = 0
            out = usage.output_tokens_details
            if out is not None and getattr(out, "reasoning_tokens", 0) is None:
                out.reasoning_tokens = 0
        return super()._handle_response_completed(event)


class GoResponsesLLM(responses.LLM):
    def chat(self, **kwargs: Any) -> responses.LLMStream:
        stream = super().chat(**kwargs)
        # The plugin builds its stream class directly; swap in the subclass before the
        # stream's task first runs (it starts on the next loop iteration).
        stream.__class__ = _GoResponsesStream
        return stream


def warm_up() -> None:
    """Build the OpenAI SDK's Responses event models now. Built lazily, the first reply
    of every session blocked the audio loop for about 0.8 s."""
    import openai.lib.streaming.responses._events  # noqa: F401  (imported on first stream)
    from openai._models import construct_type
    from openai.types.responses import ResponseStreamEvent

    response = {"id": "r", "object": "response", "created_at": 0, "model": "m", "status": "completed",
                "output": [], "tools": [], "tool_choice": "auto", "parallel_tool_calls": True,
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2,
                          "input_tokens_details": {"cached_tokens": 0},
                          "output_tokens_details": {"reasoning_tokens": 0}}}
    message = {"type": "message", "id": "m", "role": "assistant", "status": "completed",
               "content": [{"type": "output_text", "text": "Hej", "annotations": []}]}
    call = {"type": "function_call", "id": "f", "call_id": "c", "name": "n", "arguments": "{}", "status": "completed"}
    for event in (
        {"type": "response.created", "sequence_number": 0, "response": response},
        {"type": "response.in_progress", "sequence_number": 1, "response": response},
        {"type": "response.output_item.added", "sequence_number": 2, "output_index": 0, "item": message},
        {"type": "response.output_text.delta", "sequence_number": 3, "output_index": 0, "content_index": 0,
         "item_id": "m", "delta": "Hej", "logprobs": []},
        {"type": "response.function_call_arguments.delta", "sequence_number": 4, "output_index": 1,
         "item_id": "f", "delta": "{}"},
        {"type": "response.output_item.done", "sequence_number": 5, "output_index": 0, "item": message},
        {"type": "response.output_item.done", "sequence_number": 6, "output_index": 1, "item": call},
        {"type": "response.completed", "sequence_number": 7, "response": {**response, "output": [message, call]}},
    ):
        construct_type(type_=ResponseStreamEvent, value=event)


def build_llm(session_id: str, http_client: Any = None) -> llm.LLM:
    """`session_id` is the room name: Go asks for a stable id per conversation.
    `http_client` is for tests (a recorded provider stream)."""
    route = llm_route()
    log.info("tutor LLM route %s model %s api %s", route.name, route.model, route.api)
    if route.api == "responses":
        client = AsyncOpenAI(
            api_key=route.api_key,
            base_url=route.base_url,
            max_retries=0,
            default_headers={"User-Agent": USER_AGENT, "x-opencode-session": session_id},
            **({"http_client": http_client} if http_client is not None else {}),
        )
        kwargs: dict[str, Any] = {}
        if route.reasoning_effort:
            kwargs["reasoning"] = Reasoning(effort=route.reasoning_effort)
        # store=False: every request carries the full chat context, so nothing depends on
        # server-side response state and no `previous_response_id` links two sessions.
        return GoResponsesLLM(
            model=route.model, client=client, use_websocket=False, store=False, temperature=0.6, **kwargs
        )
    extra: dict[str, Any] = {}
    if route.reasoning_effort:
        extra["reasoning_effort"] = route.reasoning_effort
    return openai.LLM(
        model=route.model, base_url=route.base_url, api_key=route.api_key, temperature=0.6, **extra
    )
