"""The tutor model for one session, per the route in config.LLM_ROUTES."""

from __future__ import annotations

import json
import logging
from typing import Any

from livekit.agents import llm
from livekit.agents.llm.utils import parse_function_arguments
from livekit.plugins import openai
from livekit.plugins.openai.responses import llm as responses
from openai import AsyncOpenAI
from openai.types import Reasoning

from .config import USER_AGENT, llm_route
from .debug_log import record_active

log = logging.getLogger("open-tutor")


def heal_tool_arguments(chat_ctx: llm.ChatContext) -> int:
    """Rewrite tool-call arguments the Responses API would reject with a 400.

    On 2026-11-06 Go emitted a `show_text` call with empty arguments. The worker's
    tool runner reads that as `{}` (so the model got a useful argument error and the
    session could have recovered), but the empty string stays in the retained history
    and Go rejects every follow-up request carrying it with
    ``400 `arguments` must be valid JSON``. After enough consecutive rejections the
    AgentSession closes and the browser sits on a dead agent.

    This heals the retained items before each request, using the same reading the tool
    runner already applied: empty arguments become `"{}"`, and anything else that is
    not valid JSON goes through the framework's own repair. Arguments that parse as
    JSON are left byte-identical, and anything even the repair cannot parse is left
    untouched (still a loud provider error, never silently replaced). The tool's error
    output stays in history either way, so the model still sees what went wrong and
    can self-correct. Returns the number of items rewritten.
    """
    healed = 0
    for item in chat_ctx.items:
        if item.type != "function_call":
            continue
        arguments = item.arguments
        if not arguments or not arguments.strip():
            # Exactly what the tool runner assumed (`fnc_call.arguments or "{}"`);
            # the retained error output already describes `input_value={}`.
            item.arguments = "{}"
            healed += 1
            continue
        try:
            json.loads(arguments)
        except ValueError:
            try:
                canonical = json.dumps(parse_function_arguments(arguments), default=str)
            except ValueError:
                continue  # unrecoverable: leave it loud, don't fabricate a call
            if canonical != arguments:
                item.arguments = canonical
                healed += 1
    return healed


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
        chat_ctx = kwargs.get("chat_ctx")
        healed, names = 0, []
        if isinstance(chat_ctx, llm.ChatContext):
            healed = heal_tool_arguments(chat_ctx)
            if healed:
                # Names and counts only: arguments can hold the child's words.
                names = sorted({i.name for i in chat_ctx.items if i.type == "function_call"})
                log.warning("healed %d tool call(s) with provider-invalid arguments", healed,
                            extra={"functions": names})
        stream = super().chat(**kwargs)
        # The plugin builds its stream class directly; swap in the subclass before the
        # stream's task first runs (it starts on the next loop iteration).
        stream.__class__ = _GoResponsesStream
        if healed:
            record_active("healed_arguments", {"count": healed, "functions": sorted(names)})
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
