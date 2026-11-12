"""Behaviour tests for the bounded EmbeddingGemma 2 search proof (step 2b).

Everything here runs without the model: a recording stub encoder stands in for
EmbeddingGemma 2 to pin the plumbing (what text is sent, which passages are
skipped, what metadata survives a round trip, how cosine ranking orders). Stub
vectors say nothing about retrieval quality; the real-model test at the bottom is
opt-in behind ``OPEN_TUTOR_ML=1`` and is the only place quality is checked.
"""

import array
import json
import os
from pathlib import Path
import sys

import pytest

from open_tutor.materials.search import (
    INDEX_FORMAT,
    META_FILE,
    QUERY_PREFIX,
    VECTOR_FILE,
    EmbeddingGemmaEmbedder,
    build_index,
    document_input,
    document_title,
    ensure_supported_dtype,
    load_index,
    normalize,
    query_index,
    save_index,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from search_materials import DEFAULT_SELECT_CAP, parse_selector, select_records  # noqa: E402


class StubEmbedder:
    """Deterministic encoder that records what it was asked to embed.

    Vectors are unit axis directions chosen from the caller, so ranking order is
    fixed by construction and no similarity claim is made about real text.
    """

    model_id = "stub/model"
    model_revision = "stub-revision"
    dtype = "torch.float32"
    dimension = 3

    def __init__(self, document_vectors: list[list[float]], query_vector: list[float]):
        self.document_vectors = document_vectors
        self.query_vector = query_vector
        self.document_inputs: list[str] = []
        self.queries: list[str] = []

    def encode_documents(self, texts):
        self.document_inputs = list(texts)
        assert len(texts) == len(self.document_vectors)
        return [list(vector) for vector in self.document_vectors]

    def encode_query(self, text):
        self.queries.append(text)
        return list(self.query_vector)


def record(
    passage_id: str,
    text: str,
    *,
    heading: str = "A simple circuit",
    breadcrumbs: list[str] | None = None,
    images: list[dict] | None = None,
    section_id: str = "sec-1",
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
        "block_range": [13, 24],
        "blocks": [13, 14, 24],
        "html_is_display_content": False,
        "container": "energyandchange",
        "text": text,
        "text_complete": not images,
        "images": images or [],
        "html": "<p>never embedded</p>",
    }


# --- what text reaches the model ------------------------------------------------


def test_document_input_is_titled_owned_text_only():
    images = [{"src": "eq/1.png", "alt": "", "kind": "math-inline", "block": 0}]
    item = record("psg-1", "A cell pushes charge around the circuit.", images=images)

    assert document_title(item) == "Electric circuits > A simple circuit"
    sent = document_input(item)

    assert sent == (
        "title: Electric circuits > A simple circuit | text: "
        "A cell pushes charge around the circuit."
    )
    # The original source spans may include foreign sections: never model input.
    assert "never embedded" not in sent
    assert "<p>" not in sent


def test_document_input_without_a_title_uses_the_none_prefix():
    item = record("psg-1", "Front matter.", heading="", breadcrumbs=[])
    assert document_input(item) == "title: none | text: Front matter."


def test_repeated_breadcrumb_and_heading_is_not_duplicated():
    item = record("psg-1", "t", heading="Electric circuits", breadcrumbs=["Electric circuits"])
    assert document_title(item) == "Electric circuits"


def test_build_skips_passages_without_owned_text_and_counts_them():
    records = [
        record("psg-text", "Circuits need a closed path."),
        record("psg-empty", ""),
        record("psg-space", "   \n "),
    ]
    embedder = StubEmbedder([[1.0, 0.0, 0.0]], [1.0, 0.0, 0.0])

    index = build_index(records, embedder)

    assert len(embedder.document_inputs) == 1
    assert "Circuits need a closed path." in embedder.document_inputs[0]
    assert [entry["passage_id"] for entry in index.entries] == ["psg-text"]
    assert index.skipped_empty_text == 2


def test_build_refuses_an_index_with_nothing_to_embed():
    embedder = StubEmbedder([[1.0, 0.0, 0.0]], [1.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="No passages with text to embed"):
        build_index([record("psg-empty", "")], embedder)


def test_build_rejects_a_mismatched_or_non_finite_embedding():
    embedder = StubEmbedder([[1.0, 0.0]], [1.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="expected 3"):
        build_index([record("psg-1", "text")], embedder)

    embedder = StubEmbedder([[float("nan"), 0.0, 1.0]], [1.0, 0.0, 0.0])
    with pytest.raises(ValueError, match="non-finite"):
        build_index([record("psg-1", "text")], embedder)


def test_float16_is_refused_before_it_produces_quiet_garbage():
    with pytest.raises(RuntimeError, match="float32 or bfloat16"):
        ensure_supported_dtype("torch.float16")
    ensure_supported_dtype("torch.float32")
    ensure_supported_dtype("torch.bfloat16")


# --- metadata kept with a hit ---------------------------------------------------


def test_entries_keep_section_ids_images_and_incomplete_text_flag():
    images = [{"src": "eq/2.png", "alt": "", "kind": "math-block", "block": 1}]
    records = [
        record("psg-1", "A diagram shows the circuit.", images=images),
        record("psg-2", "The switch closes the circuit.", section_id="sec-2"),
    ]
    embedder = StubEmbedder([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], [1.0, 0.0, 0.0])

    index = build_index(records, embedder)
    hits = query_index(index, embedder, "what closes a circuit?", limit=2)

    first, second = hits
    assert first["passage_id"] == "psg-1"
    assert first["section_id"] == "sec-1"
    assert first["title"] == "Electric circuits > A simple circuit"
    assert first["book_id"] == "natural-sciences-and-technology-6"
    assert first["source_url"].endswith("book.epub")
    assert first["block_range"] == [13, 24]
    assert first["images"] == images
    assert first["text_complete"] is False  # honest: flattened text is not the content
    assert first["excerpt"].startswith("A diagram shows the circuit")
    assert second["text_complete"] is True
    assert "html" not in first  # display resolves catalogue sections, not passage slices


# --- ranking and storage --------------------------------------------------------


def test_ranking_orders_by_cosine_and_is_stable_on_ties():
    records = [
        record("psg-1", "one"),
        record("psg-2", "two"),
        record("psg-3", "three"),
    ]
    # Unit axis vectors: cosines 1.0, 0.707, 0.0 by construction (not a quality claim).
    embedder = StubEmbedder(
        [[1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 0.0, 1.0]], [1.0, 0.0, 0.0]
    )
    index = build_index(records, embedder)

    hits = query_index(index, embedder, "q", limit=3)

    assert [hit["passage_id"] for hit in hits] == ["psg-1", "psg-2", "psg-3"]
    assert [hit["rank"] for hit in hits] == [1, 2, 3]
    assert hits[0]["score"] == pytest.approx(1.0, abs=1e-6)
    assert hits[1]["score"] == pytest.approx(2**-0.5, abs=1e-6)
    assert hits[2]["score"] == pytest.approx(0.0, abs=1e-6)
    assert hits[1]["score"] > hits[2]["score"]

    tied = StubEmbedder([[1.0, 0.0, 0.0], [1.0, 0.0, 0.0]], [1.0, 0.0, 0.0])
    tied_index = build_index(records[:2], tied)
    assert [hit["passage_id"] for hit in query_index(tied_index, tied, "q")] == [
        "psg-1",
        "psg-2",
    ]
    assert len(query_index(tied_index, tied, "q", limit=1)) == 1


def test_query_is_sent_as_a_search_query_and_unnormalized_vectors_still_work():
    embedder = StubEmbedder([[2.0, 0.0, 0.0]], [0.5, 0.0, 0.0])
    index = build_index([record("psg-1", "text")], embedder)

    hits = query_index(index, embedder, "how does a cell work?")

    assert embedder.queries == ["how does a cell work?"]
    assert normalize([3.0, 4.0]) == pytest.approx([0.6, 0.8])
    assert hits[0]["score"] == pytest.approx(1.0, abs=1e-6)


def test_query_refuses_an_index_from_another_model_revision(tmp_path):
    embedder = StubEmbedder([[1.0, 0.0, 0.0]], [1.0, 0.0, 0.0])
    index = build_index([record("psg-1", "text")], embedder)

    class OtherEmbedder(StubEmbedder):
        model_revision = "other-revision"

    with pytest.raises(ValueError, match="rebuild the index"):
        query_index(index, OtherEmbedder([[1.0, 0.0, 0.0]], [1.0, 0.0, 0.0]), "q")


def test_index_round_trips_with_model_identity_and_exact_vectors(tmp_path):
    embedder = StubEmbedder([[0.6, 0.8, 0.0], [0.0, 0.0, 1.0]], [1.0, 0.0, 0.0])
    index = build_index(
        [record("psg-1", "a"), record("psg-2", "b")],
        embedder,
        corpus={"selectors": [{"book": "b", "substring": "x", "cap": 2}]},
    )
    saved = save_index(index, tmp_path / "index")

    assert (saved / META_FILE).exists() and (saved / VECTOR_FILE).exists()
    meta = json.loads((saved / META_FILE).read_text(encoding="utf-8"))
    assert meta["format"] == INDEX_FORMAT
    assert meta["model_id"] == "stub/model"
    assert meta["model_revision"] == "stub-revision"
    assert meta["dtype"] == "torch.float32"
    assert meta["corpus"]["selectors"][0]["cap"] == 2

    loaded = load_index(saved)
    assert loaded.model_revision == "stub-revision"
    assert [entry["passage_id"] for entry in loaded.entries] == ["psg-1", "psg-2"]
    assert loaded.vectors.tolist() == index.vectors.tolist()
    assert list(loaded.vector(1)) == pytest.approx([0.0, 0.0, 1.0])


def test_load_index_rejects_a_truncated_vector_file(tmp_path):
    embedder = StubEmbedder([[1.0, 0.0, 0.0]], [1.0, 0.0, 0.0])
    saved = save_index(build_index([record("psg-1", "a")], embedder), tmp_path / "index")
    saved.joinpath(VECTOR_FILE).write_bytes(array.array("f", [1.0, 0.0]).tobytes())

    with pytest.raises(ValueError, match="expected 3"):
        load_index(saved)


# --- sample selection ---------------------------------------------------------


def test_parse_selector_reads_book_substring_and_cap():
    assert parse_selector("mathematics-12:sequences and series:40") == {
        "book": "mathematics-12",
        "needle": "sequences and series",
        "cap": 40,
    }
    assert parse_selector("natural-sciences-and-technology-6:photosynthesis")["cap"] == (
        DEFAULT_SELECT_CAP
    )
    # A non-numeric tail belongs to the substring, so chapter names with a colon work.
    assert parse_selector("mathematics-12:Chapter 1: Sequences")["needle"] == (
        "chapter 1: sequences"
    )
    with pytest.raises(ValueError, match="BOOK:SUBSTRING"):
        parse_selector("natural-sciences-and-technology-6")


def test_select_records_caps_each_selector_and_keeps_corpus_order():
    circuits = [
        record(f"circuit-{index}", "t", heading="A simple circuit") for index in range(3)
    ]
    plants = [
        record(f"plant-{index}", "t", heading="Photosynthesis", breadcrumbs=["Plants"])
        for index in range(3)
    ]
    maths = [
        record(f"maths-{index}", "t", heading="Sequences", book_id="mathematics-12")
        for index in range(3)
    ]
    records = [*circuits, *plants, *maths]

    chosen = select_records(
        records,
        [
            parse_selector("natural-sciences-and-technology-6:circuit:2"),
            parse_selector("natural-sciences-and-technology-6:photosynthesis:1"),
            parse_selector("mathematics-12:sequences:2"),
        ],
        max_passages=200,
    )

    assert [item["id"] for item in chosen] == [
        "circuit-0",
        "circuit-1",
        "plant-0",
        "maths-0",
        "maths-1",
    ]
    assert len(select_records(records, [parse_selector("natural-sciences-and-technology-6:circuit:2")], max_passages=1)) == 1


# --- the real model, opt-in -----------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("OPEN_TUTOR_ML") != "1",
    reason="real EmbeddingGemma 2 download; set OPEN_TUTOR_ML=1 to run",
)
def test_real_embeddinggemma_separates_a_matching_and_an_unrelated_passage():
    embedder = EmbeddingGemmaEmbedder()
    assert embedder.dtype == "torch.float32"
    assert embedder.dimension == 768

    records = [
        record(
            "psg-light",
            "A bulb lights when the circuit is closed and current flows through it.",
            heading="A simple circuit",
        ),
        record(
            "psg-plant",
            "Plants make food from sunlight, water and carbon dioxide.",
            heading="Photosynthesis",
            breadcrumbs=["Photosynthesis"],
        ),
    ]
    index = build_index(records, embedder)
    hits = query_index(index, embedder, "why does the lamp glow?", limit=2)

    assert hits[0]["passage_id"] == "psg-light"
    assert hits[0]["score"] > hits[1]["score"]
    assert QUERY_PREFIX.startswith("task: search result")
