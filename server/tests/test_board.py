import pytest
from pydantic import ValidationError

from open_tutor.board import Ids, StepsItem, board_item, youtube_embed
from open_tutor.config import llm_route
from open_tutor.prompt import instructions, learner_context


def test_board_items_round_trip_with_discriminator():
    item = board_item.validate_python({"id": "b1", "kind": "steps", "steps": [{"tex": "3x+5=20", "op": "-5"}]})
    assert isinstance(item, StepsItem)
    with pytest.raises(ValidationError):
        board_item.validate_python({"id": "b2", "kind": "script", "src": "x"})
    with pytest.raises(ValidationError):
        StepsItem(id="b3", steps=[])


def test_ids_are_short_and_sequential():
    ids = Ids()
    assert [ids.next(), ids.next()] == ["b1", "b2"]


@pytest.mark.parametrize("url,embed", [
    ("https://www.youtube.com/watch?v=abc123XYZ_-", "https://www.youtube-nocookie.com/embed/abc123XYZ_-?rel=0"),
    ("https://youtu.be/abc123", "https://www.youtube-nocookie.com/embed/abc123?rel=0"),
    ("https://www.youtube.com/shorts/xyz", "https://www.youtube-nocookie.com/embed/xyz?rel=0"),
    ("https://sv.wikipedia.org/wiki/Dubbelbindning", None),
    ("https://www.youtube.com/watch?v=<script>", None),
])
def test_youtube_embed(url, embed):
    assert youtube_embed(url) == embed


def test_llm_route_is_explicit():
    route = llm_route({"OPENCODE_GO_API_KEY": "k"})
    assert (route.name, route.api, route.model) == ("go", "responses", "muse-spark-1.3-contributor")
    assert route.base_url == "https://opencode.ai/inference/go/openai/v1"
    assert not llm_route({"OPENCODE_GO_API_KEY": "k", "OPENROUTER_API_KEY": "k"}).base_url.startswith("https://openrouter")
    assert llm_route({"TUTOR_LLM": "gemini-dev", "GEMINI_API_KEY": "k"}).name == "gemini-dev"
    with pytest.raises(ValueError):
        llm_route({"GEMINI_API_KEY": "k"})  # the Go route never silently falls back
    with pytest.raises(ValueError):
        llm_route({"TUTOR_LLM": "spark", "OPENCODE_GO_API_KEY": "k"})  # the OpenRouter route is gone


def test_prompt_uses_learner_and_notes():
    text = learner_context({"name": "Elsa", "grade": 4, "notes": [{"at": "2026-11-01T10:00", "topic": "Division"}]})
    assert "Elsa" in text and "årskurs 4" in text and "Division" in text
    assert "first session" in learner_context({"name": "Leo"})
    assert "Never write their essay" in instructions({"name": "Leo"})
