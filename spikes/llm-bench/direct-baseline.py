#!/usr/bin/env python3
"""Direct Sweden baseline: backend A (Workers AI REST) vs B (Command Code).
Same prompt as spikes/llm-bench/worker.js. 10 runs each, streaming.
Usage: CLOUDFLARE_API_TOKEN=... COMMAND_CODE_API_KEY=... python3 direct-baseline.py
Writes JSON lines to direct-baseline.jsonl (git-ignored results, keep local).
"""
import json, os, sys, time, urllib.request

ACCT = os.environ["CLOUDFLARE_ACCOUNT_ID"]  # set this in your shell, never commit it
MODEL_A = "@cf/deepseek-ai/deepseek-v4.1-flash-1017"
MODEL_B = "deepseek/deepseek-v4.1-flash"

SYSTEM = (
 "You are Roster, a friendly spoken-English tutor for Swedish teenagers aged 13 to 16. "
 "The student hears your reply through text-to-speech and answers by voice, so every reply must sound natural when read aloud. "
 "Keep replies short: two to four sentences, at most 60 words. Use simple everyday vocabulary at CEFR level A2 to B1 and avoid idioms the student has not learned yet. "
 "Your job in each turn: react warmly to what the student just said, correct at most one mistake by modelling the right form inside your answer instead of lecturing about grammar, "
 "and then ask exactly one follow-up question that keeps the conversation going. Never ask two questions in one turn. Never use bullet points, headings, lists, emojis, or stage directions. "
 "Today you are roleplaying ordering coffee in London. You play the barista. The student is the customer. Stay in character the whole time. "
 "If the student switches to Swedish, answer in English anyway but weave in a quick translation of their Swedish words so they learn. "
 "If the student says something you do not understand, ask them to say it another way instead of guessing. "
 "Praise effort concretely before each correction, for example by naming the word they got right."
)
USER_TURN = "Hi! My name is Elin and I want to practise ordering coffee in London. Can I have a latte, please?"

def get_cf_token():
    t = os.environ.get("CLOUDFLARE_API_TOKEN")
    if t:
        return t
    sys.exit("set CLOUDFLARE_API_TOKEN (see README) to run backend A")

def read_sse(resp, t0):
    ttft_c = ttft_r = None
    content, rchars, chunks = "", 0, 0
    usage = None
    buf = b""
    while True:
        b = resp.read(65536)
        if not b:
            break
        buf += b
        *lines, buf = buf.split(b"\n")
        for line in lines:
            line = line.strip()
            if not line.startswith(b"data:"):
                continue
            p = line[5:].strip()
            if p == b"[DONE]":
                continue
            try:
                ev = json.loads(p)
            except Exception:
                continue
            if ev.get("usage"):
                usage = ev["usage"]
            d = (ev.get("choices") or [{}])[0].get("delta")
            if not d:
                continue
            now = time.perf_counter()
            c = d.get("content")
            if isinstance(c, str) and c:
                if ttft_c is None:
                    ttft_c = now - t0
                content += c
                chunks += 1
            for k in ("reasoning", "reasoning_content", "thinking"):
                r = d.get(k)
                if isinstance(r, str) and r:
                    if ttft_r is None:
                        ttft_r = now - t0
                    rchars += len(r)
    return ttft_c, ttft_r, content, rchars, chunks, usage

def run_a(token, messages):
    body = {"messages": messages, "max_tokens": 400, "stream": True, "reasoning_effort": "none"}
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{ACCT}/ai/run/{MODEL_A}",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "Accept": "text/event-stream", "User-Agent": "open-tutor-bench/0.1"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        ttft_c, ttft_r, content, rchars, chunks, usage = read_sse(r, t0)
    return {"ttft_c": ttft_c, "ttft_r": ttft_r, "total": time.perf_counter() - t0,
            "content": content, "rchars": rchars, "chunks": chunks, "usage": usage}

def run_b(key, messages):
    body = {"model": MODEL_B, "messages": messages, "max_tokens": 400, "stream": True,
            "thinking": {"type": "disabled"}, "stream_options": {"include_usage": True}}
    req = urllib.request.Request(
        "https://api.commandcode.ai/provider/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "Accept": "text/event-stream", "User-Agent": "open-tutor-bench/0.1"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        ttft_c, ttft_r, content, rchars, chunks, usage = read_sse(r, t0)
    return {"ttft_c": ttft_c, "ttft_r": ttft_r, "total": time.perf_counter() - t0,
            "content": content, "rchars": rchars, "chunks": chunks, "usage": usage}

def run_c(key, messages):
    body = {"model": "deepseek-v4.1-flash", "messages": messages, "max_tokens": 400, "stream": True,
            "thinking": {"type": "disabled"}, "stream_options": {"include_usage": True}}
    import uuid
    req = urllib.request.Request(
        "https://opencode.ai/zen/go/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "Accept": "text/event-stream", "User-Agent": "open-tutor-bench/0.1",
                 "x-opencode-session": f"bench-{uuid.uuid4()}"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        ttft_c, ttft_r, content, rchars, chunks, usage = read_sse(r, t0)
    return {"ttft_c": ttft_c, "ttft_r": ttft_r, "total": time.perf_counter() - t0,
            "content": content, "rchars": rchars, "chunks": chunks, "usage": usage}

def main():
    want = set(sys.argv[1:]) or {"a", "b", "c"}
    token = get_cf_token() if "a" in want else None
    secrets = {}
    if want & {"b", "c"}:
        auth_env = os.path.expanduser(os.environ.get("AGENT_AUTH_ENV", "agent-auth.env"))
        with open(auth_env) as f:
            for l in f:
                if l.startswith("COMMAND_CODE_API_KEY="):
                    secrets["b"] = l.split("=", 1)[1].strip()
                elif l.startswith("OPENCODE_API_KEY="):
                    secrets["c"] = l.split("=", 1)[1].strip()
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER_TURN}]
    out = open("direct-baseline.jsonl", "a")
    for i in range(10):
        for backend, fn, cred in (("a", run_a, token), ("b", run_b, secrets.get("b")), ("c", run_c, secrets.get("c"))):
            if backend not in want:
                continue
            try:
                r = fn(cred, messages)
                rec = {"run": i, "backend": backend,
                       "ttft_ms": round(r["ttft_c"] * 1000) if r["ttft_c"] else None,
                       "ttft_r_ms": round(r["ttft_r"] * 1000) if r["ttft_r"] else None,
                       "total_ms": round(r["total"] * 1000),
                       "content_chars": len(r["content"]), "chunks": r["chunks"],
                       "reasoning_chars": r["rchars"], "usage": r["usage"],
                       "first60": r["content"][:60]}
            except Exception as e:
                rec = {"run": i, "backend": backend, "error": f"{type(e).__name__}: {e}"[:200]}
            out.write(json.dumps(rec) + "\n")
            out.flush()
            print(json.dumps({k: rec.get(k) for k in ("run", "backend", "ttft_ms", "total_ms", "content_chars", "reasoning_chars", "error")}), flush=True)
            time.sleep(2)

if __name__ == "__main__":
    main()
