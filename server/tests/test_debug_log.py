"""Debug session log: enabled/disabled, content, safety and durability.

All material here is synthetic and fictional. No credentials, no child content.
"""

import json
import os
import stat

from livekit.agents import llm
from livekit.agents.metrics import AgentSessionUsage, LLMMetrics, LLMModelUsage
from livekit.agents.voice import events
from livekit.agents.voice.events import ToolCallEnded, ToolCallStarted, ToolExecutionUpdatedEvent

from open_tutor.debug_log import (
    DebugLog,
    clear_active,
    config_snapshot,
    record_active,
    sanitize_id,
    set_active,
)

LEARNER = {"name": "Leo", "grade": 7, "notes": [{"topic": "Ekvationer"}]}
SECRETS = {
    "LIVEKIT_API_SECRET": "super-secret-livekit-key",
    "OPENCODE_GO_API_KEY": "super-secret-go-key",
    "ELEVENLABS_API_KEY": "super-secret-voice-key",
    "TUTOR_ACCESS_CODE": "super-secret-code",
    "EXA_API_KEY": "super-secret-search-key",
    "TUTOR_LLM": "go",
    "TUTOR_TTS_MODEL": "eleven_v4_turbo",
    "TUTOR_DEBUG_LOG": "1",
}


def enabled_env(tmp_path, extra=None):
    env = {"TUTOR_DEBUG_LOG": "1", **SECRETS, **(extra or {})}
    return env, tmp_path / "sessions"


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_disabled_by_default_writes_nothing(tmp_path):
    debug = DebugLog.create("tutor-abc", LEARNER, "AJ_1", environ={}, base_dir=tmp_path)
    assert not debug.enabled
    debug.record("child_speech", {"text": "hej"})
    assert debug.finalize("ended") is None
    assert list(tmp_path.iterdir()) == []


def test_record_active_noops_without_session():
    clear_active()
    record_active("child_speech", {"text": "hej"})  # must not raise


def test_unwritable_base_dir_falls_back_to_disabled(tmp_path):
    debug = DebugLog.create("tutor-abc", LEARNER, "AJ_1",
                            environ={"TUTOR_DEBUG_LOG": "1"}, base_dir=tmp_path / "nope" / ".." / "proc")
    # Either disabled or still contained; it must never raise and never escape tmp_path.
    debug.record("child_speech", {"text": "hej"})
    debug.finalize("ended")
    for path in tmp_path.rglob("*"):
        assert tmp_path in path.resolve().parents or path.resolve() == tmp_path


def test_enabled_session_start_header_and_prompt_flush(tmp_path):
    env, base = enabled_env(tmp_path)
    debug = DebugLog.create("tutor-abc123", LEARNER, "AJ_test1", environ=env, base_dir=base)
    assert debug.enabled
    session_dir = base / "tutor-abc123"
    lines = (session_dir / "AJ_test1.events.jsonl")
    assert lines.is_file()  # session_start flushed promptly, before finalize
    header = read_jsonl(lines)[0]
    assert header["event"] == "session_start"
    assert header["room"] == "tutor-abc123" and header["job_id"] == "AJ_test1"
    assert header["learner"] == {"name": "Leo", "grade": 7, "notes_in": 1}
    assert header["cloud_recording"] is False  # not set in this env
    assert header["config"]["TUTOR_TTS_MODEL"] == "eleven_v4_turbo"
    assert "t_utc" in header and "t_rel_s" in header
    for secret in ("super-secret-livekit-key", "super-secret-go-key", "super-secret-voice-key",
                   "super-secret-code", "super-secret-search-key"):
        assert secret not in lines.read_text(encoding="utf-8")
    report = debug.finalize("ended_by_child")
    assert report is not None and report.name == "report.json"
    body = json.loads(report.read_text(encoding="utf-8"))
    assert body["outcome"] == "ended_by_child" and body["duration_s"] >= 0
    assert body["events"][0]["event"] == "session_start"


def test_transcript_both_sides_and_tool_content_recorded(tmp_path):
    env, base = enabled_env(tmp_path)
    debug = DebugLog.create("tutor-room9", LEARNER, "AJ_x", environ=env, base_dir=base)
    debug.record_sdk(events.UserInputTranscribedEvent(transcript="hej hej", is_final=False))
    debug.record_sdk(events.UserInputTranscribedEvent(transcript="hej, visa ekvationer", is_final=True))
    debug.record_sdk(events.ConversationItemAddedEvent(
        item=llm.ChatMessage(role="assistant", content=["Jag lägger upp det på tavlan."])))
    debug.record_sdk(events.ConversationItemAddedEvent(
        item=llm.ChatMessage(role="user", content=["Visa hur man löser 3x + 5 = 20."])))
    # Worker-injected prompts are user-role messages too, but not the child's words.
    debug.record_sdk(events.ConversationItemAddedEvent(
        item=llm.ChatMessage(role="user", content=["[Session event, not the child's words: greet.]"])))
    debug.record_sdk(events.FunctionToolsExecutedEvent(
        function_calls=[llm.FunctionCall(call_id="c1", name="show_steps",
                                        arguments='{"title": "Ekvationer", "steps": []}')],
        function_call_outputs=[llm.FunctionCallOutput(call_id="c1", name="show_steps",
                                                     output="Item b1 is now visible.", is_error=False)],
    ))
    path = debug.finalize("ended_by_child")
    body = json.loads(path.read_text(encoding="utf-8"))
    by_event = {}
    for entry in body["events"]:
        by_event.setdefault(entry["event"], []).append(entry)
    finals = [e for e in by_event["child_speech"] if e["final"]]
    assert [e["text"] for e in finals] == ["hej, visa ekvationer"]
    assistant = [e for e in by_event["chat_item"] if e.get("role") == "assistant"]
    assert assistant and "tavlan" in assistant[0]["text"]
    tools = by_event["tools_executed"][0]
    assert tools["calls"][0]["arguments"] == '{"title": "Ekvationer", "steps": []}'
    assert tools["outputs"][0]["output"] == "Item b1 is now visible."
    assert body["summary"]["child_final_turns"] == 1
    assert body["summary"]["child_typed_turns"] == 1
    assert body["summary"]["tool_calls"] == 1 and body["summary"]["tool_errors"] == 0


def test_malformed_tool_arguments_recorded_as_is_plus_heal(tmp_path):
    env, base = enabled_env(tmp_path)
    debug = DebugLog.create("tutor-room9", LEARNER, "AJ_x", environ=env, base_dir=base)
    set_active(debug)
    try:
        debug.record_sdk(events.FunctionToolsExecutedEvent(
            function_calls=[llm.FunctionCall(call_id="call_empty", name="show_text", arguments="")],
            function_call_outputs=[llm.FunctionCallOutput(
                call_id="call_empty", name="show_text",
                output="Error parsing arguments for `show_text`", is_error=True)],
        ))
        record_active("healed_arguments", {"count": 1, "functions": ["show_text"]})
    finally:
        clear_active()
    body = json.loads(debug.finalize("sdk_closed_early").read_text(encoding="utf-8"))
    tools = next(e for e in body["events"] if e["event"] == "tools_executed")
    assert tools["calls"][0]["arguments"] == ""  # the poison, byte-identical
    assert tools["outputs"][0]["is_error"] is True
    assert body["summary"]["tool_errors"] == 1
    assert body["summary"]["healed_tool_arguments"] == 1


def test_lifecycle_errors_modes_and_usage(tmp_path):
    env, base = enabled_env(tmp_path)
    debug = DebugLog.create("tutor-room9", LEARNER, "AJ_x", environ=env, base_dir=base)
    debug.record_sdk(events.AgentStateChangedEvent(old_state="listening", new_state="thinking"))
    debug.record_sdk(events.UserStateChangedEvent(old_state="listening", new_state="speaking"))
    debug.record("mode", {"old": "talking", "mode": "quiet"})
    debug.record("board_ack", {"method": "board.show", "id": "b1", "ok": True})
    debug.record("interrupt", {"where": "homework"})
    debug.record_sdk(events.UserTranscriptionTimeoutEvent(speech_duration=3.2,
                                                          vad_speech_started_at=1.0))
    debug.record_sdk(events.SessionUsageUpdatedEvent(usage=AgentSessionUsage(model_usage=[
        LLMModelUsage(provider="opencode.ai", model="muse-spark-1.3-contributor",
                      input_tokens=3080, output_tokens=137, total_tokens=3217),
    ])))
    debug.record_sdk(events.ToolExecutionUpdatedEvent(update=ToolCallStarted(
        function_call=llm.FunctionCall(call_id="c1", name="show_text", arguments="{}"))))
    debug.record_sdk(events.ToolExecutionUpdatedEvent(update=ToolCallEnded(
        call_id="c1", id="c1_final", message="Saved.", status="done")))
    debug.record_sdk(events.CloseEvent(reason=events.CloseReason.TASK_COMPLETED))
    body = json.loads(debug.finalize("ended_by_child").read_text(encoding="utf-8"))
    kinds = [e["event"] for e in body["events"]]
    assert kinds[:1] == ["session_start"]
    assert "speech_state" in kinds and "mode" in kinds and "board_ack" in kinds
    assert "interrupt" in kinds and "transcription_timeout" in kinds
    usage = next(e for e in body["events"] if e["event"] == "usage")
    assert usage["usage"]["model_usage"][0]["model"] == "muse-spark-1.3-contributor"
    assert usage["usage"]["model_usage"][0]["input_tokens"] == 3080
    started = next(e for e in body["events"] if e.get("update") == "tool_call_started")
    assert started["call_id"] == "c1" and started["name"] == "show_text"
    ended = next(e for e in body["events"] if e.get("update") == "tool_call_ended")
    assert ended["status"] == "done" and ended["message"] == "Saved."
    assert body["summary"]["close_reason"] == "task_completed"
    assert body["summary"]["mode_changes"][0][1] == "quiet"
    assert len(body["summary"]["mode_changes"]) == 1


def test_error_event_never_crashes_recorder(tmp_path):
    env, base = enabled_env(tmp_path)
    debug = DebugLog.create("tutor-room9", LEARNER, "AJ_x", environ=env, base_dir=base)
    debug.record_sdk(events.ErrorEvent(error=ValueError("boom"), source="probe"))
    debug.record_sdk(events.MetricsCollectedEvent(metrics=LLMMetrics(
        label="x", request_id="r", timestamp=0.0, duration=0.1, ttft=0.05,
        cancelled=False, completion_tokens=3, prompt_tokens=5,
        prompt_cached_tokens=0, total_tokens=8, tokens_per_second=30.0)))
    body = json.loads(debug.finalize("ended_by_child").read_text(encoding="utf-8"))
    errors = [e for e in body["events"] if e["event"] == "provider_error"]
    assert errors and errors[0]["error_type"] == "ValueError"
    assert body["summary"]["provider_errors"] == 1


def test_room_id_cannot_escape_base_dir(tmp_path):
    env, base = enabled_env(tmp_path)
    debug = DebugLog.create("../../../etc/cron.d/x", LEARNER, "AJ_1", environ=env, base_dir=base)
    assert debug.enabled
    assert debug.directory is not None
    assert base.resolve() in debug.directory.resolve().parents
    assert ".." not in debug.directory.name
    debug.finalize("ended")
    assert not (tmp_path / "etc").exists()


def test_private_permissions(tmp_path):
    env, base = enabled_env(tmp_path)
    debug = DebugLog.create("tutor-room9", LEARNER, "AJ_x", environ=env, base_dir=base)
    path = debug.finalize("ended_by_child")
    assert stat.S_IMODE(os.stat(base).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(debug.directory).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    events_file = debug.directory / "AJ_x.events.jsonl"
    assert stat.S_IMODE(os.stat(events_file).st_mode) == 0o600


def test_config_snapshot_is_allowlist_only():
    snapshot = config_snapshot({**SECRETS, "TUTOR_CLOUD_RECORDING": "1", "RANDOM": "x"})
    assert snapshot["TUTOR_LLM"] == "go"
    assert snapshot["TUTOR_CLOUD_RECORDING"] == "1"
    assert "RANDOM" not in snapshot
    for key in snapshot:
        assert "KEY" not in key and "SECRET" not in key and "CODE" not in key
    assert "super-secret-livekit-key" not in json.dumps(snapshot)


def test_sanitize_id():
    assert sanitize_id("tutor-abc_123") == "tutor-abc_123"
    assert "/" not in sanitize_id("../../etc/x") and ".." not in sanitize_id("../../etc/x")
    assert sanitize_id("") == "unknown"


def test_finalize_after_error_still_writes_report(tmp_path):
    env, base = enabled_env(tmp_path)
    debug = DebugLog.create("tutor-room9", LEARNER, "AJ_x", environ=env, base_dir=base)
    debug.record("child_speech", {"final": True, "text": "hej"})
    path = debug.finalize("error: RuntimeError: boom")
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["outcome"].startswith("error:")
    assert len(body["events"]) == 2  # session_start + the turn: crash keeps evidence
