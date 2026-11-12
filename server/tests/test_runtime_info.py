"""Sessionsinfo metadata: contract shape, allowlisted content, URL redaction.

No live sessions, no network, no secrets: engines are built the same way the
worker builds them, with throwaway test keys, and the payload must never
contain those keys or any credential-like value.
"""

import json

import pytest

from open_tutor import runtime_info
from open_tutor.agent import build_stt, build_tts
from open_tutor.config import llm_route
from open_tutor.dialogue_tts import DialogueTTS
from open_tutor.tutor_llm import build_llm


@pytest.fixture
def go_env(monkeypatch):
    monkeypatch.setenv("TUTOR_LLM", "go")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "test-key-not-a-secret")
    for name in ("TUTOR_LLM_MODEL", "TUTOR_LLM_BASE_URL", "TUTOR_LLM_REASONING"):
        monkeypatch.delenv(name, raising=False)
    for name in ("TUTOR_ADAPTIVE_INTERRUPTION", "TUTOR_MIN_ENDPOINT",
                 "TUTOR_DEBUG_LOG", "TUTOR_DEBUG_ARTIFACTS", "TUTOR_CLOUD_RECORDING"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    # Throwaway key: build_tts() requires one, and the leak tests below
    # prove it never reaches the published payload.
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-not-a-secret")


def sections(payload):
    assert payload["version"] == 1
    out = {}
    for section in payload["sections"]:
        assert isinstance(section["title"], str) and section["title"]
        fields = {}
        for field in section["fields"]:
            assert isinstance(field["label"], str) and field["label"]
            assert isinstance(field["value"], str) and field["value"]
            fields[field["label"]] = field["value"]
        out[section["title"]] = fields
    return out


def test_redact_url_strips_secrets_but_keeps_host_and_path():
    assert runtime_info.redact_url("https://user:pass@example.com:8448/a/b?x=1#frag") == \
        "https://example.com:8448/a/b"
    assert runtime_info.redact_url("wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input") == \
        "wss://api.elevenlabs.io/v1/text-to-dialogue/stream-input"
    assert runtime_info.redact_url("https://opencode.ai/inference/go/openai/v1") == \
        "https://opencode.ai/inference/go/openai/v1"


def test_redact_url_rejects_non_urls_and_empty():
    assert runtime_info.redact_url("https://example.com:invalid/path") == ""
    assert runtime_info.redact_url("https://[::1]:8448/a?token=secret") == "https://[::1]:8448/a"
    assert runtime_info.redact_url("") == ""
    assert runtime_info.redact_url(None) == ""
    assert runtime_info.redact_url("not a url") == ""
    assert runtime_info.redact_url("ftp://example.com/x") == ""
    assert runtime_info.redact_url("Bearer test-key-not-a-secret") == ""


def test_default_voice_payload_matches_actual_engines(go_env, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-not-a-secret")
    for name in ("TUTOR_TTS", "TUTOR_TTS_MODEL", "TUTOR_TTS_VOICE"):
        monkeypatch.delenv(name, raising=False)
    llm = build_llm("tutor-room-1")
    stt = build_stt()
    tts = build_tts()
    assert isinstance(tts, DialogueTTS)

    payload = runtime_info.build_runtime_info(
        room="tutor-room-1", llm=llm, stt=stt, tts=tts,
        adaptive=False, min_endpoint_delay=0.6, max_endpoint_delay=4.0,
    )
    by_title = sections(payload)
    assert by_title["Språkmodell"]["Modell"] == "muse-spark-1.3-contributor"
    assert by_title["Språkmodell"]["Tjänst"] == "OpenCode Go"
    assert by_title["Språkmodell"]["Resonemang"] == "minimal"
    assert "opencode.ai" in by_title["Språkmodell"]["Värd"]
    assert by_title["Lyssning (tal till text)"]["Modell"] == "stt-rt-v5"
    assert by_title["Lyssning (tal till text)"]["Leverantör"] == "Soniox"
    assert "soniox.com" in by_title["Lyssning (tal till text)"]["Värd"]
    assert by_title["Röst (text till tal)"]["Modell"] == "eleven_v4_turbo"
    assert by_title["Röst (text till tal)"]["Leverantör"] == "ElevenLabs"
    assert "text-to-dialogue/stream-input" in by_title["Röst (text till tal)"]["Anslutning"]
    assert by_title["Avbrott och felsökning"]["Avbrottsläge"] == "röststyrt (VAD)"
    assert by_title["Avbrott och felsökning"]["Felsökningslogg"] == "av"

    dumped = json.dumps(payload, ensure_ascii=False)
    assert "test-key-not-a-secret" not in dumped
    assert "api_key" not in dumped.lower()


def test_gemini_dev_route_reports_no_explicit_reasoning(go_env, monkeypatch):
    monkeypatch.setenv("TUTOR_LLM", "gemini-dev")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-a-secret")
    route = llm_route()
    assert route.reasoning_effort is None
    llm = build_llm("tutor-room-1")
    payload = runtime_info.build_runtime_info(
        room="tutor-room-1", llm=llm, stt=build_stt(), tts=build_tts(),
    )
    by_title = sections(payload)
    assert by_title["Språkmodell"]["Resonemang"] == "standard (inget explicit val)"
    assert "GEMINI_API_KEY" not in json.dumps(payload)
    assert "test-key-not-a-secret" not in json.dumps(payload)


def test_deepgram_engine_reports_actual_expressivity_and_endpoint(go_env, monkeypatch):
    monkeypatch.setenv("TUTOR_TTS", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-key-not-a-secret")
    monkeypatch.setenv("TUTOR_TTS_EXPRESSIVITY", "1")
    tts = build_tts()
    payload = runtime_info.build_runtime_info(
        room="r", llm=build_llm("r"), stt=build_stt(), tts=tts,
    )
    by_title = sections(payload)
    assert by_title["Röst (text till tal)"]["Modell"] == "flux-ludvig-sv"
    assert by_title["Röst (text till tal)"]["Uttrycksfullhet"] == "1"
    assert "deepgram.com" in by_title["Röst (text till tal)"]["Anslutning"]
    assert "test-key-not-a-secret" not in json.dumps(payload)


def test_unknown_engine_reports_unknown_instead_of_guessing(go_env):
    class MysteryTTS:
        provider = "Mystery"
        model = "mystery-1"
        sample_rate = 16000
        capabilities = None

    payload = runtime_info.build_runtime_info(
        room="r", llm=build_llm("r"), stt=build_stt(), tts=MysteryTTS(),
    )
    by_title = sections(payload)
    assert by_title["Röst (text till tal)"]["Anslutning"] == "okänd"
    assert by_title["Röst (text till tal)"]["Modell"] == "mystery-1"


def test_debug_flags_report_on_off(go_env, monkeypatch):
    monkeypatch.setenv("TUTOR_DEBUG_LOG", "1")
    monkeypatch.setenv("TUTOR_DEBUG_ARTIFACTS", "1")
    payload = runtime_info.build_runtime_info(
        room="r", llm=build_llm("r"), stt=build_stt(), tts=build_tts(),
    )
    by_title = sections(payload)
    assert by_title["Avbrott och felsökning"]["Felsökningslogg"] == "på"
    assert by_title["Avbrott och felsökning"]["Bildlagring"] == "på"
    assert by_title["Avbrott och felsökning"]["Molninspelning"] == "av"


@pytest.mark.asyncio
async def test_publish_merges_with_existing_mode_attribute(go_env, monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-not-a-secret")
    for name in ("TUTOR_TTS", "TUTOR_TTS_MODEL", "TUTOR_TTS_VOICE"):
        monkeypatch.delenv(name, raising=False)

    seen = {}

    class FakeParticipant:
        def __init__(self):
            self.attributes = {"tutor.mode": "talking"}

        async def set_attributes(self, attrs):
            seen.update(attrs)

    class FakeRoom:
        name = "tutor-room-9"
        local_participant = FakeParticipant()

    payload = await runtime_info.publish_runtime_info(
        FakeRoom(), llm=build_llm("r"), stt=build_stt(), tts=build_tts(),
    )
    assert payload["version"] == 1
    assert seen["tutor.mode"] == "talking"
    assert json.loads(seen[runtime_info.RUNTIME_ATTR])["version"] == 1
