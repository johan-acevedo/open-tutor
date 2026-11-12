"""Behaviour tests for the tutor-facing material search adapter (step 4a).

Everything here runs without torch: a stub encoder stands in for EmbeddingGemma 2
and the runtime's model factory is monkeypatched. The tests pin the parts that
decide whether the tutor gets honest, distinct section candidates or a clear
"unavailable" answer: explicit configuration only, one load per process, the
revision recorded by the index, section de-duplication, off-loop blocking work,
and the wording of the tool result.
"""

import asyncio
import json
from pathlib import Path
import threading

import pytest

from open_tutor.agent import MATERIAL_SEARCH_NOTE, Tutor
from open_tutor.materials import runtime as material_runtime
from open_tutor.materials.runtime import (
    MAX_CANDIDATES,
    MATERIAL_INDEX_VAR,
    MaterialsUnavailable,
    MaterialSearchRuntime,
    configured_index_dir,
    load_runtime,
    search_material,
    section_candidates,
)
from open_tutor.materials.search import build_index, load_index, save_index


class StubEmbedder:
    """Deterministic encoder: axis vectors, so ranking order is fixed by construction."""

    dtype = "torch.float32"

    def __init__(self, model_id="stub/model", model_revision="stub-revision", dimension=3):
        self.model_id = model_id
        self.model_revision = model_revision
        self.dimension = dimension
        self.document_vectors: list[list[float]] = []
        self.queries: list[str] = []
        self.query_vector = [1.0, 0.0, 0.0]

    def encode_documents(self, texts):
        assert len(texts) == len(self.document_vectors)
        return [list(vector) for vector in self.document_vectors]

    def encode_query(self, text):
        self.queries.append(text)
        return list(self.query_vector)

    def describe(self):
        return {
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "dtype": self.dtype,
            "dimension": self.dimension,
        }


def record(
    passage_id: str,
    text: str,
    *,
    section_id: str,
    heading: str = "A simple circuit",
    breadcrumbs: list[str] | None = None,
    images: list[dict] | None = None,
    book_id: str = "natural-sciences-and-technology-6",
) -> dict:
    """A passage record shaped like ``Passage.to_dict()``."""
    return {
        "id": passage_id,
        "ordinal": 1,
        "section_id": section_id,
        "book_id": book_id,
        "book_sha256": "sha",
        "grade": 6,
        "language": "en",
        "source_url": "https://example.invalid/book.epub",
        "license": "CC-BY",
        "license_url": "https://creativecommons.org/licenses/by/3.0/",
        "heading": heading,
        "breadcrumbs": breadcrumbs if breadcrumbs is not None else ["Electric circuits"],
        "document_href": "text/ch13.xhtml",
        "fragment": "ch13",
        "source_href": "ch13.xhtml",
        "blocks": [13, 14],
        "container": "energyandchange",
        "text": text,
        "text_complete": not images,
        "images": images or [],
        "html": "<p>never embedded</p>",
    }


def write_index(directory: Path, records: list[dict], vectors: list[list[float]],
                *, revision: str = "stub-revision", corpus: dict | None = None) -> Path:
    """Build and save a real index file with stub vectors."""
    builder = StubEmbedder(model_revision=revision)
    builder.document_vectors = vectors
    index = build_index(records, builder, corpus=corpus or {})
    return save_index(index, directory)


def patch_embedder(monkeypatch, embedder: StubEmbedder, calls: list | None = None):
    def factory(model_id: str, revision: str):
        if calls is not None:
            calls.append((model_id, revision, threading.get_ident()))
        return embedder

    monkeypatch.setattr(material_runtime, "_embedding_model", factory)


@pytest.fixture(autouse=True)
def clean_runtime(monkeypatch):
    """Every test starts with no process runtime and no ambient configuration."""
    material_runtime.reset_runtime()
    monkeypatch.delenv(MATERIAL_INDEX_VAR, raising=False)
    yield
    material_runtime.reset_runtime()


@pytest.fixture
def circuit_index(tmp_path, monkeypatch):
    """A three-section index: two passages in section A, one each in B and C."""
    records = [
        record("a1", "A cell pushes charge around a closed circuit.", section_id="sec-aaaaaaaaaaaaaaaa"),
        record("a2", "The lamp lights because charge flows.", section_id="sec-aaaaaaaaaaaaaaaa"),
        record("b1", "Photosynthesis uses light energy.", section_id="sec-bbbbbbbbbbbbbbbb",
               heading="Photosynthesis", breadcrumbs=["Life and living"]),
        record("c1", "A series circuit has one path.", section_id="sec-cccccccccccccccc"),
    ]
    vectors = [
        [1.0, 0.0, 0.0],
        [0.9, 0.2, 0.0],
        [0.0, 1.0, 0.0],
        [0.0, 0.0, 1.0],
    ]
    directory = write_index(tmp_path / "eval-index", records, vectors,
                            corpus={"selectors": [{"book": "natural-sciences-and-technology-6"}],
                                    "selected_passages": 4})
    monkeypatch.setenv(MATERIAL_INDEX_VAR, str(directory))
    return directory


class FakeParticipant:
    async def perform_rpc(self, **_kwargs):
        raise AssertionError("material search must not touch the board")


class FakeRoom:
    local_participant = FakeParticipant()


def tutor() -> Tutor:
    return Tutor({"name": "Leo", "grade": 7}, FakeRoom())


def parse_result(value: str) -> dict:
    return json.loads(value)


# --- distinct section candidates -------------------------------------------------


def test_ranking_reduces_to_one_candidate_per_section(circuit_index):
    runtime = MaterialSearchRuntime(
        index=load_index(circuit_index), embedder=StubEmbedder(), index_dir=circuit_index)
    results = runtime.search("why does the lamp light up", limit=5)

    section_ids = [candidate["section_id"] for candidate in results]
    assert section_ids == ["sec-aaaaaaaaaaaaaaaa", "sec-bbbbbbbbbbbbbbbb", "sec-cccccccccccccccc"]
    # The section appears once, with its best passage, not twice for two passages.
    first = results[0]
    assert first["passage_id"] == "a1"
    assert first["rank"] == 1
    assert [candidate["rank"] for candidate in results] == [1, 2, 3]
    scores = [candidate["score"] for candidate in results]
    assert scores == sorted(scores, reverse=True)


def test_section_candidates_keep_source_metadata_and_completeness():
    ranked = [
        {
            "rank": 1,
            "section_id": "sec-1",
            "passage_id": "p1",
            "book_id": "natural-sciences-and-technology-6",
            "title": "Electric circuits > A simple circuit",
            "breadcrumbs": ["Electric circuits"],
            "heading": "A simple circuit",
            "grade": 6,
            "language": "en",
            "source_url": "https://example.invalid/book.epub",
            "license": "CC-BY",
            "excerpt": "A cell pushes charge.",
            "text_complete": False,
            "images": [{"src": "eq/1.png"}],
            "score": 0.71,
        }
    ]
    candidate = section_candidates(ranked, limit=5)[0]
    assert candidate["section_id"] == "sec-1"
    assert candidate["source_excerpt"] == "A cell pushes charge."
    assert candidate["title"] == "Electric circuits > A simple circuit"
    assert candidate["breadcrumbs"] == ["Electric circuits"]
    assert (candidate["book_id"], candidate["grade"], candidate["language"]) == (
        "natural-sciences-and-technology-6", 6, "en")
    assert candidate["source_url"].startswith("https://example.invalid/")
    assert candidate["license"] == "CC-BY"
    assert candidate["text_complete"] is False
    assert candidate["image_count"] == 1
    assert candidate["score"] == 0.71


def test_candidate_limit_caps_distinct_sections():
    ranked = [
        {"rank": index + 1, "section_id": f"sec-{index}", "passage_id": f"p{index}",
         "score": 1.0 - index / 100}
        for index in range(9)
    ]
    assert len(section_candidates(ranked, limit=2)) == 2
    assert len(section_candidates(ranked)) == MAX_CANDIDATES
    assert MAX_CANDIDATES == 5
    with pytest.raises(ValueError):
        section_candidates(ranked, limit=0)


# --- configuration, revision and lazy loading -----------------------------------


def test_runtime_loads_the_exact_revision_recorded_in_the_index(monkeypatch, circuit_index):
    calls: list = []
    patch_embedder(monkeypatch, StubEmbedder(model_revision="stub-revision"), calls)

    runtime = material_runtime.runtime_for_process()

    assert calls == [("stub/model", "stub-revision", calls[0][2])]
    assert runtime.index.model_revision == "stub-revision"
    assert runtime.describe()["index_model"]["model_revision"] == "stub-revision"
    assert runtime.describe()["model"]["dtype"] == "torch.float32"


def test_a_host_without_configuration_is_unavailable(monkeypatch):
    calls: list = []
    patch_embedder(monkeypatch, StubEmbedder(), calls)

    for environ in ({}, {MATERIAL_INDEX_VAR: "   "}):
        with pytest.raises(MaterialsUnavailable, match=MATERIAL_INDEX_VAR):
            configured_index_dir(environ)
    assert calls == []


def test_a_missing_or_unbuilt_index_directory_is_unavailable(tmp_path, monkeypatch):
    calls: list = []
    patch_embedder(monkeypatch, StubEmbedder(), calls)

    monkeypatch.setenv(MATERIAL_INDEX_VAR, str(tmp_path / "absent"))
    with pytest.raises(MaterialsUnavailable, match="no index.json"):
        material_runtime.runtime_for_process()

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(MaterialsUnavailable, match="no index.json"):
        load_runtime(empty)
    assert calls == []


def test_missing_optional_ml_dependencies_are_unavailable(monkeypatch, circuit_index):
    def factory(model_id: str, revision: str):
        raise ImportError("No module named 'torch'")

    monkeypatch.setattr(material_runtime, "_embedding_model", factory)
    with pytest.raises(MaterialsUnavailable, match="--group ml"):
        material_runtime.runtime_for_process()


def test_a_non_fp32_encoder_is_refused(monkeypatch, circuit_index):
    class HalfEmbedder(StubEmbedder):
        dtype = "torch.float16"

    patch_embedder(monkeypatch, HalfEmbedder())
    with pytest.raises(MaterialsUnavailable, match="float32"):
        material_runtime.runtime_for_process()


def test_the_model_is_loaded_once_per_process(monkeypatch, circuit_index):
    calls: list = []
    patch_embedder(monkeypatch, StubEmbedder(), calls)

    runtime = material_runtime.runtime_for_process()
    again = material_runtime.runtime_for_process()
    runtime.search("first")
    runtime.search("second")

    assert again is runtime
    assert len(calls) == 1


def test_a_changed_configuration_loads_its_own_runtime(tmp_path, monkeypatch):
    calls: list = []
    patch_embedder(monkeypatch, StubEmbedder(), calls)
    first = write_index(tmp_path / "one", [record("p1", "First.", section_id="sec-1")],
                        [[1.0, 0.0, 0.0]])
    second = write_index(tmp_path / "two", [record("p2", "Second.", section_id="sec-2")],
                         [[1.0, 0.0, 0.0]])

    monkeypatch.setenv(MATERIAL_INDEX_VAR, str(first))
    one = material_runtime.runtime_for_process()
    monkeypatch.setenv(MATERIAL_INDEX_VAR, str(second))
    two = material_runtime.runtime_for_process()

    assert one is not two
    assert len(calls) == 2
    assert {entry["section_id"] for entry in two.index.entries} == {"sec-2"}


async def test_loading_and_inference_run_off_the_event_loop(monkeypatch, circuit_index):
    main_thread = threading.get_ident()
    calls: list = []
    patch_embedder(monkeypatch, StubEmbedder(), calls)
    search_threads: list[int] = []
    original = MaterialSearchRuntime.search

    def recording_search(self, query, limit=MAX_CANDIDATES):
        search_threads.append(threading.get_ident())
        return original(self, query, limit)

    monkeypatch.setattr(MaterialSearchRuntime, "search", recording_search)
    await search_material("varför lyser lampan")

    assert calls[0][2] != main_thread
    assert search_threads and search_threads[0] != main_thread


async def test_search_reports_a_bounded_index_and_the_query(monkeypatch, circuit_index):
    patch_embedder(monkeypatch, StubEmbedder())
    payload = await search_material("  hur   lyser   lampan  ")

    assert payload["query"] == "hur lyser lampan"
    assert payload["index"]["passages"] == 4
    assert payload["index"]["sections"] == 3
    assert payload["index"]["books"] == ["natural-sciences-and-technology-6"]
    assert 1 <= len(payload["candidates"]) <= MAX_CANDIDATES


async def test_blank_query_is_rejected_before_loading(monkeypatch):
    def factory(model_id: str, revision: str):
        raise AssertionError("a blank query must not load a model")

    monkeypatch.setattr(material_runtime, "_embedding_model", factory)
    with pytest.raises(ValueError):
        await search_material("   ")


# --- the agent tool ---------------------------------------------------------------


async def test_the_tool_returns_labelled_distinct_candidates(monkeypatch, circuit_index):
    patch_embedder(monkeypatch, StubEmbedder())
    result = parse_result(await tutor().search_materials(None, query="varför lyser lampan"))

    assert result["note"] == MATERIAL_SEARCH_NOTE
    assert "source text" in result["note"] and "not something the child can see" in result["note"]
    assert "not a confidence" in result["note"]
    assert result["index"]["passages"] == 4
    assert [candidate["section_id"] for candidate in result["candidates"]] == [
        "sec-aaaaaaaaaaaaaaaa", "sec-bbbbbbbbbbbbbbbb", "sec-cccccccccccccccc"]
    first = result["candidates"][0]
    assert first["source_excerpt"]
    assert first["passage_id"] == "a1"
    assert isinstance(first["score"], float)


async def test_blank_query_returns_guidance_without_a_search(monkeypatch, circuit_index):
    def boom(*_args, **_kwargs):
        raise AssertionError("blank query must not search")

    monkeypatch.setattr("open_tutor.agent.search_material", boom)
    answer = await tutor().search_materials(None, query="  ")
    assert "No search query" in answer and "nothing was shown" in answer


async def test_unconfigured_material_search_leaves_teaching_working(monkeypatch):
    def factory(model_id: str, revision: str):
        raise AssertionError("nothing to load without an index")

    monkeypatch.setattr(material_runtime, "_embedding_model", factory)
    answer = await tutor().search_materials(None, query="fotosyntes")
    assert "unavailable" in answer and MATERIAL_INDEX_VAR in answer
    assert "Continue teaching in words" in answer


async def test_a_search_failure_is_reported_not_raised(monkeypatch, circuit_index):
    async def boom(_query, limit=MAX_CANDIDATES):
        raise RuntimeError("inference exploded")

    monkeypatch.setattr("open_tutor.agent.search_material", boom)
    answer = await tutor().search_materials(None, query="fotosyntes")
    assert "failed" in answer and "Continue teaching in words" in answer


async def test_a_cold_load_and_search_stay_responsive_together(monkeypatch, circuit_index):
    """One search per call, but one load: many learners never reload the weights."""
    calls: list = []
    patch_embedder(monkeypatch, StubEmbedder(), calls)
    t = tutor()
    await asyncio.gather(
        t.search_materials(None, query="krets"),
        t.search_materials(None, query="fotosyntes"),
    )
    assert len(calls) == 1
