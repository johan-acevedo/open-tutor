"""Recorded Commons responses + scripted vision replies; no network or model key."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from screen.tools.page_images import without_images, PageImages, image_slots

FIXTURES = Path(__file__).parent / "fixtures" / "commons-images"
SEARCH = json.loads((FIXTURES / "search.json").read_text())
PHOTO = (FIXTURES / "colosseum.jpg").read_bytes()
ACCEPT = json.dumps({"accept": True, "reason": "Relevant Roman building, no answer shown."})
REJECT = json.dumps({"accept": False, "reason": "The labels reveal the requested answer.",
                     "fallback": "<p>Vi undersöker hur valven bär byggnaden.</p>"})

# The three candidates in the recorded search, in the order the page prefers.
RANK0 = "File:Colosseum in Rome-April 2007-1- copie 2B.jpg"
RANK1 = "File:Colosseum in Rome, Italy - April 2007.jpg"
RANK2 = "File:Cross Colosseum Rome Italy.jpg"


def scripted(verdicts: dict[str, str], delays: dict[str, float] | None = None,
             log: list | None = None, raises: dict[str, Exception] | None = None):
    """A review callable that decides by candidate title, with per-title delays.

    Keyed by title, not by call order: concurrent reviews settle in whatever
    order their download finishes, so an order-based script would be flaky."""
    async def review(user, photo, hedge=True):
        title = next((key for key in verdicts if key in user), RANK0)
        if log is not None:
            log.append({"title": title, "hedge": hedge, "at": time.monotonic()})
        await asyncio.sleep((delays or {}).get(title, 0.0))
        if raises and title in raises:
            raise raises[title]
        return verdicts[title]
    return review


def transport(payload=SEARCH, *, download_error=False):
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "commons.wikimedia.org":
            return httpx.Response(200, json=payload)
        if download_error:
            return httpx.Response(200, content=b"<html>Not a picture</html>", headers={"content-type": "image/jpeg"})
        return httpx.Response(200, content=PHOTO, headers={"content-type": "image/jpeg"})

    return httpx.MockTransport(handle), requests


@pytest.mark.parametrize("markup", [
    '<ot-image query="Rom" alt="Byggnaden"></ot-image>',
    '<ot-image src="https://commons.wikimedia.org/wiki/File:Colosseum_in_Rome,_Italy_-_April_2007.jpg" credit="model invention"></ot-image>',
])
@pytest.mark.asyncio
async def test_only_reviewed_commons_src_and_authoritative_credit_reach_page(markup):
    http, requests = transport()
    review = AsyncMock(return_value=ACCEPT)
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Årskurs 6, romersk arkitektur", review, time.monotonic() + 5, client=client)
        body = await images.prepare("<h1>Rom</h1>" + markup)
        slots = image_slots(body)
        assert len(slots) == 1
        attrs = slots[0].attrs
        assert "query" not in attrs and attrs["src"].startswith("https://thumb.wikimedia.org/")
        assert attrs["credit"] == "Bild: Diliff, CC BY-SA 2.5, Wikimedia Commons"
        # The top of the list is judged at once: the best-ranked acceptance
        # wins, and its better-ranked peers are the only ones it waited for.
        assert review.call_count == 3
        user, photo = review.call_args.args
        assert photo == PHOTO and "Årskurs 6" in user and "gives away an answer" in user
        accepted = [e for e in images.events if e["decision"] == "accepted"]
        assert len(accepted) == 1 and accepted[0]["rank"] == 0
        assert accepted[0]["bytes"] == len(PHOTO)
        assert len(accepted[0]["sha256"]) == 64
        assert all({"download_s", "review_s", "finished_s", "start_s"} <= set(e)
                   for e in images.events)
        before = len(requests)
        assert await images.prepare(body) == body  # unchanged approved source is not re-reviewed
        assert len(requests) == before


@pytest.mark.asyncio
async def test_rejection_then_acceptance_logs_both_candidates():
    http, requests = transport()
    review = scripted({RANK0: REJECT, RANK1: ACCEPT, RANK2: REJECT}, delays={RANK1: 0.05})
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Rom", review, time.monotonic() + 5, client=client)
        body = await images.prepare('<ot-image query="Colosseum" alt="Rom"></ot-image>')
    assert image_slots(body)
    assert [e["rank"] for e in images.events] == sorted(e["rank"] for e in images.events)
    first, second = images.events[0], images.events[1]
    assert first["decision"] == "rejected" and first["title"] == RANK0
    assert first["reason"] == "The labels reveal the requested answer."
    assert second["decision"] == "accepted" and second["rank"] == 1
    assert len(requests) == 4  # the search and all three bounded downloads


@pytest.mark.parametrize("reply", [REJECT, "not JSON", '{"accept":"true","reason":"ambiguous"}', '{"accept":true,"reason":""}'])
@pytest.mark.asyncio
async def test_rejected_or_invalid_verdict_falls_back_without_revealing_hidden_text(reply):
    http, _ = transport()
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Rom", AsyncMock(return_value=reply), time.monotonic() + 5, client=client)
        body = await images.prepare('<ot-image id="bild" later alt="Svaret är dolt" query="Colosseum"></ot-image>')
    assert not image_slots(body)
    assert '<section id="bild" later="">' in body
    assert "query=" not in body and "https://" not in body
    assert all(e["decision"] == "rejected" for e in images.events)


@pytest.mark.parametrize("payload,src", [
    ({"query": {"pages": {}}}, 'query="missing"'),
    (SEARCH, 'src="https://example.org/not-commons.jpg"'),
])
@pytest.mark.asyncio
async def test_no_candidate_or_foreign_src_uses_text_without_a_vision_call(payload, src):
    http, requests = transport(payload)
    review = AsyncMock()
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Rom", review, time.monotonic() + 5, client=client)
        body = await images.prepare(f'<ot-image id="bild" {src} alt="Valv"></ot-image><p>Fortsätt här.</p>')
    review.assert_not_called()
    assert "Valv" in body and "Fortsätt här." in body and not image_slots(body)
    assert images.events and images.events[0]["decision"] == "rejected"
    assert len(requests) == (1 if "missing" in src else 0)


@pytest.mark.asyncio
async def test_download_rejects_html_before_vision():
    http, _ = transport(download_error=True)
    review = AsyncMock()
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Rom", review, time.monotonic() + 5, client=client)
        assert not image_slots(await images.prepare('<ot-image query="Colosseum"></ot-image>'))
    review.assert_not_called()
    assert all("ValueError" in e["reason"] for e in images.events)


@pytest.mark.asyncio
async def test_budget_expiry_cancels_review_and_keeps_the_page_with_audit():
    http, _ = transport()
    cancelled = []

    async def review(user, photo, hedge=True):
        try:
            await asyncio.Future()
        finally:
            cancelled.append(user)

    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Rom", review, time.monotonic() + 0.4, client=client)
        started = time.monotonic()
        body = await images.prepare('<h1>Rom</h1><ot-image id="bild" query="Colosseum" alt="Valv"></ot-image><p>Slut.</p>')
        elapsed = time.monotonic() - started
    assert cancelled  # every review that started was cancelled, not orphaned
    assert elapsed < 2  # the budget cut the wait, not the hanging reviews
    assert "<h1>Rom</h1>" in body and "<p>Slut.</p>" in body and not image_slots(body)
    assert all(e["decision"] == "rejected" for e in images.events)
    assert all(e["title"].startswith("File:") for e in images.events)
    assert all("budget" in e["reason"] for e in images.events)
    assert not [task for task in asyncio.all_tasks()
                if task.get_name().startswith("page-image-review-") and not task.done()]


@pytest.mark.asyncio
async def test_text_pages_and_exhausted_budget_do_not_touch_network_or_model():
    http, requests = transport()
    review = AsyncMock()
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Rom", review, time.monotonic() - 1, client=client)
        assert await images.prepare('<h1>Rom</h1>') == '<h1>Rom</h1>'
        assert not images.events and images.seconds == 0
        body = await images.prepare('<ot-image id="bild" query="Colosseum" alt="Valv"></ot-image>')
    assert not image_slots(body) and "Valv" in body
    assert not requests
    review.assert_not_called()


def test_offsets_nested_and_unclosed_tags_keep_surrounding_teaching_text():
    body = '<h1>Å</h1>\n<ot-image query="a"><ot-image query="b"/></ot-image><p>Slut</p>'
    slots = image_slots(body)
    assert len(slots) == 1 and body[slots[0].start:slots[0].end].startswith('<ot-image')
    broken = '<ot-image query="a"><p>Keep me</p>'
    slot = image_slots(broken)[0]
    assert broken[slot.end:] == '<p>Keep me</p>'
    nested = '<ot-image query="a"><ot-image src="https://example.invalid/x.png"></ot-image><p>Kvar</p>'
    slots = image_slots(nested)
    assert [s.attrs for s in slots] == [{"query": "a"}, {"src": "https://example.invalid/x.png"}]
    assert nested[slots[1].start:slots[1].end] == '<ot-image src="https://example.invalid/x.png"></ot-image>'
    deep = '<ot-image>' * 1000 + '<p>Keep</p>'
    slots = image_slots(deep)  # no RecursionError; the teaching text survives
    assert len(slots) == 1000 and deep[slots[-1].end:] == '<p>Keep</p>'
    assert without_images(deep) == '<p>Keep</p>'


# Concurrent reviews: the ranking rule, the deadline, cancellation, isolation.
# Each test scripts the review by candidate title, so settlement order is
# controlled instead of hoped for.

SLOT = '<ot-image query="Colosseum" alt="Rom"></ot-image>'


async def run_slot(review, *, deadline_s=5.0, concurrency=3, slots=SLOT, store=None):
    http, requests = transport()
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Rom", review, time.monotonic() + deadline_s, client=client,
                            review_concurrency=concurrency, image_store=store)
        started = time.monotonic()
        body = await images.prepare(slots)
    return body, images, requests, time.monotonic() - started


def accepted_ranks(images):
    return [event["rank"] for event in images.events if event["decision"] == "accepted"]


@pytest.mark.asyncio
async def test_a_better_ranked_acceptance_wins_even_when_it_finishes_last():
    """Rank beats speed: the slower better-ranked candidate is still the pick."""
    review = scripted({RANK0: ACCEPT, RANK1: ACCEPT, RANK2: ACCEPT},
                      delays={RANK0: 0.15, RANK1: 0.0, RANK2: 0.0})
    body, images, _, elapsed = await run_slot(review)
    assert image_slots(body)[0].attrs["credit"].startswith("Bild:")
    assert accepted_ranks(images) == [0]
    assert elapsed >= 0.15  # it did wait for the better-ranked review
    lower = [e for e in images.events if e["rank"] == 1][0]
    assert lower["decision"] == "rejected"  # judged good, but superseded


@pytest.mark.asyncio
async def test_a_lower_ranked_acceptance_waits_for_its_betters_to_finish():
    """Two quick acceptances below rank 0 do not pre-empt a better-ranked review."""
    review = scripted({RANK0: REJECT, RANK1: ACCEPT, RANK2: ACCEPT},
                      delays={RANK0: 0.15, RANK1: 0.0, RANK2: 0.0})
    body, images, _, elapsed = await run_slot(review)
    assert accepted_ranks(images) == [1]
    assert elapsed >= 0.15
    assert image_slots(body)


@pytest.mark.asyncio
async def test_the_deadline_takes_the_best_acceptance_that_finished():
    """A better-ranked review that never finishes must not cost the slot its image."""
    hanging = asyncio.Event()

    async def review(user, photo, hedge=True):
        if RANK0 in user:
            try:
                await asyncio.Future()
            finally:
                hanging.set()
            raise AssertionError("unreachable")
        await asyncio.sleep(0)
        return ACCEPT

    body, images, _, elapsed = await run_slot(review, deadline_s=0.6)
    assert hanging.is_set()  # the slow review was cancelled, not left running
    assert elapsed < 1.5  # and the slot did not wait for it
    assert accepted_ranks(images) == [1]  # best-ranked acceptance that did finish
    assert image_slots(body)


@pytest.mark.asyncio
async def test_a_winner_cancels_and_drains_every_outstanding_review():
    cancelled = []

    async def review(user, photo, hedge=True):
        if RANK0 in user:
            return ACCEPT
        try:
            await asyncio.Future()
        finally:
            cancelled.append(user)

    body, images, requests, elapsed = await run_slot(review)
    assert image_slots(body) and accepted_ranks(images) == [0]
    assert len(cancelled) == 2  # both losers were cancelled mid-review
    assert elapsed < 1
    cancelled_rows = [e for e in images.events if e["rank"] in (1, 2)]
    assert all(e["decision"] == "rejected" for e in cancelled_rows)
    assert all("better-ranked candidate was accepted" in e["reason"] for e in cancelled_rows)
    assert not [task for task in asyncio.all_tasks()
                if task.get_name().startswith("page-image-review-") and not task.done()]


@pytest.mark.asyncio
async def test_reviews_of_one_slot_run_concurrently():
    peak, running = 0, 0

    async def review(user, photo, hedge=True):
        nonlocal peak, running
        running += 1
        peak = max(peak, running)
        try:
            await asyncio.sleep(0.15)
            return REJECT
        finally:
            running -= 1

    _, images, _, elapsed = await run_slot(review)
    assert peak == 3  # the whole top of the list is judged at once
    assert elapsed < 0.4  # not three reviews one after another
    assert len(images.events) == 3 and not accepted_ranks(images)


@pytest.mark.asyncio
async def test_one_review_setting_keeps_today_s_sequential_order():
    order, peak, running = [], 0, 0

    async def review(user, photo, hedge=True):
        nonlocal peak, running
        running += 1
        peak = max(peak, running)
        order.append(next(title for title in (RANK0, RANK1, RANK2) if title in user))
        try:
            await asyncio.sleep(0.01)
            return REJECT
        finally:
            running -= 1

    _, images, _, _ = await run_slot(review, concurrency=1)
    assert peak == 1 and order == [RANK0, RANK1, RANK2]
    assert [e["rank"] for e in images.events] == [0, 1, 2]


@pytest.mark.asyncio
async def test_a_failing_review_only_rejects_that_candidate():
    review = scripted({RANK0: REJECT, RANK1: ACCEPT, RANK2: ACCEPT},
                      delays={RANK1: 0.05}, raises={RANK0: RuntimeError("provider died")})
    body, images, _, _ = await run_slot(review)
    assert image_slots(body)  # the slot still gets a picture
    assert accepted_ranks(images) == [1]
    failed = images.events[0]
    assert failed["rank"] == 0 and failed["decision"] == "rejected"
    assert failed["reason"] == "download/review failed: RuntimeError"


@pytest.mark.asyncio
async def test_only_the_best_ranked_review_hedges():
    """N concurrent reviews cost N provider calls, not 2N: one hedge per slot."""
    log = []
    review = scripted({RANK0: REJECT, RANK1: REJECT, RANK2: REJECT}, log=log)
    await run_slot(review)
    assert [entry["hedge"] for entry in log] == [True, False, False]


@pytest.mark.asyncio
async def test_the_page_wide_gate_bounds_reviews_across_slots():
    """Prefetched slots resolve concurrently; the job still caps reviews in flight."""
    peak, running = 0, 0

    async def review(user, photo, hedge=True):
        nonlocal peak, running
        running += 1
        peak = max(peak, running)
        try:
            await asyncio.sleep(0.1)
            return REJECT
        finally:
            running -= 1

    http, _ = transport()
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Rom", review, time.monotonic() + 10, client=client, review_concurrency=2)
        slots = image_slots(SLOT + SLOT.replace("Rom", "Amfiteater"))
        decisions = await asyncio.gather(*(images.resolve_slot(slot) for slot in slots))
    assert len(decisions) == 2 and peak <= 2


class RecordingStore:
    """Catch only what would be served: the bytes a child could see."""

    def __init__(self):
        self.saved = []

    def save(self, data, mime):
        self.saved.append(bytes(data))
        return hashlib.sha256(bytes(data)).hexdigest() + ".jpg"

    def url_for(self, filename):
        return f"/api/images/{filename}"


@pytest.mark.asyncio
async def test_only_the_winning_parallel_bytes_reach_the_store(monkeypatch):
    """A Parallel acceptance that loses to a better-ranked one is never stored."""
    from screen.tools import parallel_images as parallel

    monkeypatch.setattr(parallel, "_default_resolve", lambda host: ["93.184.216.34"])
    first = b"\xff\xd8\xff\xe0first-picture"
    second = b"\xff\xd8\xff\xe0second-picture"
    payload = {"search_id": "s", "session_id": "s", "results": [
        {"title": "Wrong flag map", "image_url": "https://example.com/a.jpg",
         "source_page_url": "https://example.com/a"},
        {"title": "Historical map", "image_url": "https://example.com/b.jpg",
         "source_page_url": "https://example.com/b"},
    ]}

    async def get(url, pins):
        return 200, {"content-type": "image/jpeg"}, first if url.endswith("a.jpg") else second

    monkeypatch.setattr(parallel, "_fetch", get)
    monkeypatch.setenv("PARALLEL_API_KEY", "test-key")

    def handle(request):
        if request.url.host == "api.parallel.ai":
            return httpx.Response(200, json=payload)
        raise AssertionError(f"unexpected host {request.url.host}")

    review = scripted({"Wrong flag map": ACCEPT, "Historical map": ACCEPT},
                      delays={"Wrong flag map": 0.15, "Historical map": 0.0})
    store = RecordingStore()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        images = PageImages("Årskurs 6, stormaktstiden", review, time.monotonic() + 5,
                            client=client, image_mode="parallel", image_store=store)
        body = await images.prepare(SLOT)
    attrs = image_slots(body)[0].attrs
    assert attrs["src"] == f"/api/images/{hashlib.sha256(first).hexdigest()}.jpg"
    assert store.saved == [first]  # only the winner's bytes, never the superseded one
    accepted_event = [e for e in images.events if e["decision"] == "accepted"][0]
    assert accepted_event["rank"] == 0 and accepted_event["served_as"] == attrs["src"]
