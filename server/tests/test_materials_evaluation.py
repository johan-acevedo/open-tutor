"""Behaviour tests for the declared step 2c retrieval evaluation.

No model and no EPUB are touched here. The fixtures pin what the evaluation
promises: declared labels resolve before ranking, section-level scoring collapses
duplicate passages, the lexical baseline reports its language treatment honestly,
saved query vectors reproduce a report, and absent-topic rows never enter the
accuracy numerator.
"""

import json
from pathlib import Path

import pytest

from open_tutor.materials.evaluation import (
    LexicalIndex,
    build_evaluation_report,
    default_dataset_path,
    evaluate_sections,
    iter_queries,
    load_dataset,
    load_query_vectors,
    resolve_relevant_sections,
    save_query_vectors,
    section_ranking,
    tokenize,
)
from open_tutor.materials.search import build_index


class StubEmbedder:
    model_id = "stub/model"
    model_revision = "stub-revision"
    dtype = "torch.float32"
    dimension = 3

    def __init__(self, document_vectors, query_vector):
        self.document_vectors = document_vectors
        self.query_vector = query_vector
        self.document_inputs = []
        self.queries = []

    def encode_documents(self, texts):
        self.document_inputs = list(texts)
        return [list(vector) for vector in self.document_vectors]

    def encode_query(self, text):
        self.queries.append(text)
        return list(self.query_vector)


def passage_record(
    passage_id: str,
    section_id: str,
    heading: str,
    text: str,
    text_complete: bool = True,
    book_id: str = "stub-book",
) -> dict:
    return {
        "id": passage_id,
        "section_id": section_id,
        "book_id": book_id,
        "grade": 6,
        "language": "en",
        "heading": heading,
        "breadcrumbs": [],
        "text": text,
        "text_complete": text_complete,
        "images": [] if text_complete else [{"src": "eq/1.png", "kind": "math-inline"}],
    }


def section(section_id: str, heading: str, book_id: str = "stub-book", breadcrumbs=None) -> dict:
    return {
        "section_id": section_id,
        "book_id": book_id,
        "breadcrumbs": breadcrumbs or [],
        "heading": heading,
    }


# --- the declared dataset -------------------------------------------------------


def test_declared_dataset_has_enough_groups_books_languages_and_absent_topics():
    dataset = load_dataset()

    assert dataset["format"] == "open-tutor-retrieval-eval/1"
    assert len(dataset["topic_groups"]) >= 6
    assert len(dataset["concepts"]) >= 12
    assert len(dataset["absent_topics"]) >= 1
    assert dataset["max_passages"] <= 400
    books = {group["book_id"] for group in dataset["topic_groups"]}
    assert len(books) >= 6
    assert any("mathematics" in book for book in books)
    assert any("sciences" in book or "natural-sciences" in book for book in books)
    for concept in dataset["concepts"]:
        assert concept["questions"]["en"].strip()
        assert concept["questions"]["sv"].strip()
        assert concept["relevant_sections"]
    assert len(dataset["_sha256"]) == 64


def test_dataset_validation_refuses_too_few_concepts(tmp_path):
    dataset = json.loads(default_dataset_path().read_text(encoding="utf-8"))
    dataset["concepts"] = dataset["concepts"][:1]
    broken = tmp_path / "dataset.json"
    broken.write_text(json.dumps(dataset), encoding="utf-8")

    with pytest.raises(ValueError, match="at least twelve concepts"):
        load_dataset(broken)


def test_every_concept_and_absent_topic_has_paired_english_and_swedish_queries():
    dataset = load_dataset()
    queries = iter_queries(dataset)

    assert len(queries) == 2 * (len(dataset["concepts"]) + len(dataset["absent_topics"]))
    by_item = {}
    for query in queries:
        by_item.setdefault(query["item_id"], set()).add(query["language"])
    assert all(languages == {"en", "sv"} for languages in by_item.values())
    assert len({query["query_id"] for query in queries}) == len(queries)


def test_declared_labels_resolve_to_exact_pool_sections_or_fail_loudly():
    dataset = {
        "concepts": [
            {
                "id": "concept-a",
                "relevant_sections": [
                    {
                        "book_id": "b",
                        "breadcrumbs": ["Chapter 1"],
                        "heading": "1.1 A section",
                    }
                ],
            }
        ]
    }
    sections = [
        section("sec-1", "1.1 A section", book_id="b", breadcrumbs=["Chapter 1"]),
        section("sec-2", "Other section", book_id="b", breadcrumbs=["Chapter 2"]),
    ]

    resolved = resolve_relevant_sections(dataset, sections)

    assert resolved == {
        "concept-a": [
            {
                "section_id": "sec-1",
                "book_id": "b",
                "title": "Chapter 1 > 1.1 A section",
            }
        ]
    }

    missing = {
        "concepts": [
            {
                "id": "concept-a",
                "relevant_sections": [
                    {"book_id": "b", "breadcrumbs": ["Chapter 1"], "heading": "Nope"}
                ],
            }
        ]
    }
    with pytest.raises(ValueError, match="not in the candidate pool"):
        resolve_relevant_sections(missing, sections)

    ambiguous = [*sections, section("sec-3", "1.1 A section", book_id="b", breadcrumbs=["Chapter 1"])]
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_relevant_sections(dataset, ambiguous)


# --- section-level scoring ------------------------------------------------------


def result(rank, passage_id, section_id, complete=True):
    return {
        "rank": rank,
        "passage_id": passage_id,
        "section_id": section_id,
        "book_id": "b",
        "title": f"Section {section_id}",
        "score": 0.9 - rank / 100,
        "text_complete": complete,
    }


def test_section_ranking_collapses_duplicate_passages_and_preserves_best_rank():
    ranked = section_ranking(
        [
            result(1, "p1", "s1", complete=False),
            result(2, "p2", "s1", complete=True),
            result(3, "p3", "s2"),
        ]
    )

    assert [item["section_id"] for item in ranked] == ["s1", "s2"]
    assert ranked[0]["passage_ids"] == ["p1", "p2"]
    assert ranked[0]["first_rank"] == 1
    assert ranked[0]["text_complete"] is False
    assert ranked[0]["any_text_complete"] is True
    assert ranked[1]["first_rank"] == 3


def test_section_level_top1_and_top5_ignore_duplicate_passage_count():
    passages = [
        result(1, "p1", "s1"),
        result(2, "p2", "s1"),
        result(3, "p3", "s2"),
        result(4, "p4", "s3"),
    ]
    ranked = section_ranking(passages)

    hit = evaluate_sections(ranked, {"s2"}, passage_results=passages)
    assert hit["top1"] is False
    assert hit["top5"] is True
    assert hit["hit_section_rank"] == 2
    # The first five passage results contain p2 from the section already at rank 1.
    assert hit["passage_level_duplicate_sections_in_top5"] == 1
    assert hit["top5_sections"][1]["relevant"] is True
    assert hit["top5_sections"][0]["relevant"] is False

    miss = evaluate_sections(ranked, {"s9"}, passage_results=passages)
    assert miss["top1"] is False
    assert miss["top5"] is False
    assert miss["hit_section_rank"] is None

    absent = evaluate_sections(ranked, set(), passage_results=passages)
    assert absent["scored"] is False
    assert absent["top1"] is None and absent["top5"] is None


# --- lexical baseline -----------------------------------------------------------


def test_lexical_baseline_ranks_shared_english_terms_and_reports_zero_swedish_overlap():
    records = [
        passage_record(
            "p1", "s1", "Electric circuits", "A cell pushes charge around a closed circuit."
        ),
        passage_record("p2", "s2", "Photosynthesis", "Plants make food from sunlight."),
    ]
    lexical = LexicalIndex.from_records(records)

    english = lexical.search("battery charge circuit")
    assert english[0]["passage_id"] == "p1"
    assert english[0]["score"] > english[1]["score"]
    assert lexical.overlap("closed circuit")["matched_terms"] == ["circuit", "closed"]

    swedish = lexical.overlap("varför lyser lampan?")
    assert swedish["zero_overlap"] is True
    assert swedish["matched_terms"] == []
    swedish_hits = lexical.search("varför lyser lampan?")
    assert [hit["passage_id"] for hit in swedish_hits] == ["p1", "p2"]
    assert all(hit["score"] == 0.0 for hit in swedish_hits)
    # Same input, same ranking: the baseline is deterministic on zero scores.
    assert swedish_hits == lexical.search("varför lyser lampan?")
    assert tokenize("The CIRCUIT and the cell") == ["circuit", "cell"]


# --- saved vectors, report, determinism -----------------------------------------


def report_fixture():
    records = [
        passage_record("p1", "s1", "Electric circuits", "A cell pushes charge around a closed circuit."),
        passage_record(
            "p2", "s1", "Electric circuits", "A switch opens and closes the circuit.", text_complete=False
        ),
        passage_record("p3", "s2", "Photosynthesis", "Plants make food from sunlight."),
    ]
    embedder = StubEmbedder(
        [[1.0, 0.0, 0.0], [0.9, 0.1, 0.0], [0.0, 1.0, 0.0]], [1.0, 0.0, 0.0]
    )
    index = build_index(
        records,
        embedder,
        corpus={
            "evaluation": {
                "dataset_id": "fixture",
                "dataset_sha256": "fixture-sha",
                "dataset_path": "fixture.json",
                "candidate_pool": {"indexed_passages": 3},
            }
        },
    )
    corpus = [
        {
            "passage_id": entry["passage_id"],
            "section_id": entry["section_id"],
            "book_id": entry["book_id"],
            "title": entry["title"],
            "text": records[position]["text"],
            "text_complete": entry["text_complete"],
        }
        for position, entry in enumerate(index.entries)
    ]
    payload = {
        "dataset_id": "fixture",
        "dataset_sha256": "fixture-sha",
        "model_id": "stub/model",
        "model_revision": "stub-revision",
        "relevant_sections": {
            "concept-a": [
                {
                    "section_id": "s1",
                    "book_id": "stub-book",
                    "title": "Electric circuits",
                }
            ]
        },
    }
    queries = [
        {
            "query_id": "concept-a:en",
            "item_id": "concept-a",
            "kind": "concept",
            "topic_group": "fixture-group",
            "language": "en",
            "text": "circuit",
        },
        {
            "query_id": "absent-x:en",
            "item_id": "absent-x",
            "kind": "absent",
            "topic_group": "absent",
            "language": "en",
            "text": "mobile phone screen",
        },
    ]
    vectors = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    return index, corpus, payload, queries, vectors


def test_report_scores_only_declared_labels_and_keeps_absent_topics_separate():
    index, corpus, payload, queries, vectors = report_fixture()

    report = build_evaluation_report(index, corpus, payload, queries, vectors)

    embedding = report["methods"]["embeddinggemma"]
    assert embedding["overall"]["scored_queries"] == 1
    assert embedding["overall"]["top1"]["count"] == 1
    assert embedding["overall"]["top5_sections"]["count"] == 1
    assert embedding["overall"]["passage_level_duplicate_sections_in_top5"] == 1
    assert report["absent_topics"]["embeddinggemma"]["queries"] == 1
    assert report["absent_topics"]["lexical_bm25"]["queries"] == 1
    assert report["determinism"]["identical"] is True
    assert len(report["determinism"]["sha256"]) == 64
    # s1 has one complete and one incomplete passage; p2 is the image-incomplete one.
    assert report["image_incomplete"]["pool"]["incomplete_text_passages"] == 1
    assert report["image_incomplete"]["relevant_sections"]["concept-a"]["all_passages_incomplete"] is False
    # The absent question has no declared label, so it cannot appear as a miss.
    assert embedding["misses"]["top5_miss_count"] == 0


def test_saved_query_vectors_reproduce_the_same_report(tmp_path):
    index, corpus, payload, queries, vectors = report_fixture()
    first = build_evaluation_report(index, corpus, payload, queries, vectors)

    save_query_vectors(
        tmp_path,
        queries,
        vectors,
        dimension=3,
        meta={
            "dataset_sha256": payload["dataset_sha256"],
            "model_id": payload["model_id"],
            "model_revision": payload["model_revision"],
            "relevant_sections": payload["relevant_sections"],
        },
    )
    saved_payload, saved_queries, saved_vectors = load_query_vectors(tmp_path)
    second = build_evaluation_report(index, corpus, saved_payload, saved_queries, saved_vectors)

    assert saved_queries == queries
    assert saved_vectors[1].tolist() == pytest.approx([0.0, 1.0, 0.0])
    assert json.dumps(second, sort_keys=True) == json.dumps(first, sort_keys=True)


def test_query_vector_file_rejects_a_wrong_dimension(tmp_path):
    with pytest.raises(ValueError, match="expected 3"):
        save_query_vectors(
            tmp_path,
            [{"query_id": "q", "item_id": "q", "kind": "concept", "topic_group": "g", "language": "en", "text": "q"}],
            [[1.0, 0.0]],
            dimension=3,
            meta={},
        )
