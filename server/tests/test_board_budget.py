"""Board generation budget: output-cap extension + provider-boundary errors.

Covers the fix/board-generation-budget candidate: the board_budget.js
extension really caps provider output through a fake pi hook, the app CLI
loads that exact extension file and forwards the validated cap, the
subprocess is killed AND reaped on timeout/cancel, and provider errors or
length-truncated replies are rejected before they can become boards.
"""

import asyncio
import json
import os
import shutil
import subprocess

import pytest

import open_tutor.board_model as board_model

NODE = shutil.which("node")
EXTENSION_URL = board_model.BOARD_BUDGET_EXTENSION.as_uri()

NODE_HARNESS = r"""
const { default: factory } = await import(process.env.BOARD_EXT_URL);
const registrations = [];
const fakePi = { on: (name, fn) => { registrations.push([name, fn]); } };
await factory(fakePi);
const hook = Object.fromEntries(registrations)["before_provider_request"];
if (typeof hook !== "function") {
  console.log(JSON.stringify({ hook: false }));
  process.exit(0);
}
const run = async (payload) => {
  const before = JSON.stringify(payload);
  const out = await hook({ payload });
  return {
    result: out === undefined ? payload : out,
    replaced: out !== undefined,
    mutated: JSON.stringify(payload) !== before,
  };
};
console.log(JSON.stringify({
  hook: true,
  capped: await run({ max_tokens: 100000, keep: "yes\"..." }),
  small: await run({ max_tokens: 1000, keep: "yes" }),
  completion: await run({ max_completion_tokens: 200000 }),
  bare: await run({ temperature: 0.5 }),
}));
"""


def run_node_harness(env_extra):
    env = {**os.environ, "BOARD_EXT_URL": EXTENSION_URL, **env_extra}
    proc = subprocess.run(
        [NODE, "--input-type=module"], input=NODE_HARNESS,
        capture_output=True, text=True, timeout=60, env=env)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_extension_caps_output_and_preserves_other_fields():
    out = run_node_harness({"BOARD_MAX_TOKENS": "16384"})
    assert out["hook"] is True
    assert out["capped"]["result"] == {"max_tokens": 16384, "keep": "yes\"..."}
    assert out["capped"]["replaced"] is True
    assert out["capped"]["mutated"] is False
    # A lower existing limit is respected, other fields untouched.
    assert out["small"]["result"] == {"max_tokens": 1000, "keep": "yes"}
    assert out["small"]["replaced"] is False
    assert out["completion"]["result"] == {"max_completion_tokens": 16384}
    # No cap fields: payload passes through unchanged (hook returns undefined).
    assert out["bare"]["result"] == {"temperature": 0.5}
    assert out["bare"]["replaced"] is False


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_extension_honours_env_cap():
    out = run_node_harness({"BOARD_MAX_TOKENS": "8000"})
    assert out["capped"]["result"]["max_tokens"] == 8000


def test_board_max_tokens_validated_at_env_boundary(monkeypatch):
    monkeypatch.setenv("BOARD_MAX_TOKENS", "8000")
    assert board_model._board_max_tokens() == 8000
    monkeypatch.setenv("BOARD_MAX_TOKENS", "bogus")
    assert board_model._board_max_tokens() == 16384
    monkeypatch.setenv("BOARD_MAX_TOKENS", "0")
    assert board_model._board_max_tokens() == 16384
    monkeypatch.delenv("BOARD_MAX_TOKENS", raising=False)
    assert board_model._board_max_tokens() == 16384


class FakeBoardProc:
    def __init__(self):
        self.argv = ()
        self.env = {}
        self.killed = False
        self.waited = False
        self.returncode = 0
        self.lines: tuple = ()
        self.behavior = "ok"

    async def communicate(self):
        if self.behavior == "timeout":
            raise asyncio.TimeoutError()
        if self.behavior == "cancel":
            raise asyncio.CancelledError()
        return ("\n".join(self.lines).encode(), b"")

    def kill(self):
        self.killed = True

    async def wait(self):
        self.waited = True
        return self.returncode


@pytest.fixture
def fake_pi(monkeypatch):
    procs: list = []
    state = {"lines": (), "returncode": 0, "behavior": "ok"}

    async def spawn(*argv, **kwargs):
        proc = FakeBoardProc()
        proc.argv = argv
        proc.env = kwargs.get("env") or {}
        proc.lines = state["lines"]
        proc.returncode = state["returncode"]
        proc.behavior = state["behavior"]
        procs.append(proc)
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    return state, procs


def end_line(text="", stop_reason="stop", error=None):
    msg = {"role": "assistant", "content": [{"type": "text", "text": text}],
           "stopReason": stop_reason}
    if error is not None:
        msg["errorMessage"] = error
    return json.dumps({"type": "message_end", "message": msg})


async def test_cli_loads_budget_extension_and_forwards_cap(fake_pi):
    state, procs = fake_pi
    state["lines"] = (end_line("<!doctype html><html></html>"),)
    await board_model.call_board_model("sys", "hi")
    argv = procs[0].argv
    ext = argv[argv.index("--extension") + 1]
    assert ext == str(board_model.BOARD_BUDGET_EXTENSION)
    assert procs[0].env["BOARD_MAX_TOKENS"] == str(board_model.BOARD_MAX_TOKENS)


async def test_timeout_kills_and_reaps(fake_pi):
    state, procs = fake_pi
    state["behavior"] = "timeout"
    with pytest.raises(TimeoutError):
        await board_model.call_board_model("sys", "hi")
    assert procs[0].killed and procs[0].waited


async def test_cancel_kills_and_reaps(fake_pi):
    state, procs = fake_pi
    state["behavior"] = "cancel"
    with pytest.raises(asyncio.CancelledError):
        await board_model.call_board_model("sys", "hi")
    assert procs[0].killed and procs[0].waited


async def test_provider_error_rejected(fake_pi):
    state, _ = fake_pi
    state["lines"] = (end_line("", stop_reason="error", error="boom 529"),)
    with pytest.raises(RuntimeError, match="boom 529"):
        await board_model.call_board_model("sys", "hi")


async def test_length_truncation_rejected(fake_pi):
    state, _ = fake_pi
    state["lines"] = (end_line("<!doctype html><html><body>cut",
                               stop_reason="length"),)
    with pytest.raises(ValueError, match="truncated"):
        await board_model.call_board_model("sys", "hi")


async def test_nonzero_exit_without_reply_rejected(fake_pi):
    state, _ = fake_pi
    state["lines"] = ("pi: auth failed",)
    state["returncode"] = 1
    with pytest.raises(RuntimeError, match="exit 1"):
        await board_model.call_board_model("sys", "hi")


async def test_render_board_rejects_html_missing_close_tag(monkeypatch):
    async def partial(system, user_message):
        return "<!doctype html><html><body><p>cut off mid-stream"

    async def no_screenshot(html, width, height):
        raise AssertionError("truncated HTML must never be screenshotted")

    calls = []
    async def counting(system, user_message):
        calls.append(1)
        return await partial(system, user_message)

    monkeypatch.setattr(board_model, "call_board_model", counting)
    monkeypatch.setattr(board_model, "screenshot_board", no_screenshot)
    with pytest.raises(ValueError, match="no HTML document"):
        await board_model.render_board("need", "background")
    assert len(calls) == 2  # one retry before giving up


async def test_render_board_accepts_complete_document(monkeypatch):
    async def complete(system, user_message):
        return "<!doctype html><html><body><p>done</p></body></html>note"

    async def no_chromium(html, width, height):
        return None

    monkeypatch.setattr(board_model, "call_board_model", complete)
    monkeypatch.setattr(board_model, "screenshot_board", no_chromium)
    result = await board_model.render_board("need", "background")
    assert result["html"].endswith("</html>")
    assert result["note"] == "note"
