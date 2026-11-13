"""Recorded Commons responses + scripted vision replies; no network or model key."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from screen.tools.page_images import PageImages, image_slots

FIXTURES = Path(__file__).parent / "fixtures" / "commons-images"
SEARCH = json.loads((FIXTURES / "search.json").read_text())
PHOTO = (FIXTURES / "colosseum.jpg").read_bytes()
ACCEPT = json.dumps({"accept": True, "reason": "Relevant Roman building, no answer shown."})
REJECT = json.dumps({"accept": False, "reason": "The labels reveal the requested answer.",
                     "fallback": "<p>Vi undersöker hur valven bär byggnaden.</p>"})


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
        assert review.call_count == 1
        user, photo = review.call_args.args
        assert photo == PHOTO and "Årskurs 6" in user and "gives away an answer" in user
        assert images.events[-1]["decision"] == "accepted"
        assert images.events[-1]["bytes"] == len(PHOTO)
        assert len(images.events[-1]["sha256"]) == 64
        before = len(requests)
        assert await images.prepare(body) == body  # unchanged approved source is not re-reviewed
        assert len(requests) == before


@pytest.mark.asyncio
async def test_rejection_then_acceptance_logs_both_candidates():
    http, requests = transport()
    review = AsyncMock(side_effect=[REJECT, ACCEPT])
    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Rom", review, time.monotonic() + 5, client=client)
        body = await images.prepare('<ot-image query="Colosseum" alt="Rom"></ot-image>')
    assert image_slots(body)
    assert [e["decision"] for e in images.events] == ["rejected", "accepted"]
    assert images.events[0]["reason"] == "The labels reveal the requested answer."
    assert len(requests) == 3  # search and two bounded downloads


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
    cancelled = asyncio.Event()

    async def review(user, photo):
        try:
            await asyncio.Future()
        finally:
            cancelled.set()

    async with httpx.AsyncClient(transport=http) as client:
        images = PageImages("Rom", review, time.monotonic() + 0.03, client=client)
        body = await images.prepare('<h1>Rom</h1><ot-image id="bild" query="Colosseum" alt="Valv"></ot-image><p>Slut.</p>')
    assert cancelled.is_set()
    assert "<h1>Rom</h1>" in body and "<p>Slut.</p>" in body and not image_slots(body)
    assert any(e.get("title", "").startswith("File:") and "budget" in e["reason"] for e in images.events)


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
