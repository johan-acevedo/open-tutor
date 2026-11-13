#!/usr/bin/env python3
"""Rerunnable retrieval evaluation for material-library step 2c.

Two commands, both small and explicit:

    # One real model build of a bounded, declared candidate pool.
    bin/with-env uv run --group ml python scripts/evaluate_material_search.py build \\
        --revision f9972ac22e696a105c482202646979e33e4b5a1e

    # Rerun both methods from saved vectors and saved passage text. No model.
    bin/with-env uv run python scripts/evaluate_material_search.py report --details

The evaluation index lives outside Git, separately from the step 2b proof index:
``~/.local/share/open-tutor/materials/retrieval-eval-index`` (honouring
``XDG_DATA_HOME``). Nothing here is a general benchmark, a production search
API, or an abstention classifier.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

from open_tutor.materials.catalogue import DEFAULT_BOOKS_PATH, default_data_dir
from open_tutor.materials.evaluation import (
    CORPUS_FILE,
    QUERY_FILE,
    build_evaluation_report,
    default_dataset_path,
    iter_queries,
    load_baseline_corpus,
    load_dataset,
    load_query_vectors,
    resolve_relevant_sections,
    save_baseline_corpus,
    save_query_vectors,
)
from open_tutor.materials.passages import extract_catalogue_passages
from open_tutor.materials.search import (
    MODEL_ID,
    QUERY_PREFIX,
    EmbeddingGemmaEmbedder,
    build_index,
    default_index_dir,
    load_index,
    save_index,
)

from search_materials import parse_selector, select_records, selector_match_count

EVAL_INDEX_NAME = "retrieval-eval-index"


def default_eval_index_dir() -> Path:
    """Separate from the step 2b proof index, still outside Git."""
    return default_index_dir().with_name(EVAL_INDEX_NAME)


def _sections(records: list[dict]) -> list[dict]:
    """Unique catalogue sections represented in the candidate pool."""
    sections: list[dict] = []
    seen: set[str] = set()
    for record in records:
        if record["section_id"] in seen:
            continue
        seen.add(record["section_id"])
        sections.append(
            {
                "section_id": record["section_id"],
                "book_id": record["book_id"],
                "breadcrumbs": list(record.get("breadcrumbs") or []),
                "heading": record.get("heading") or "",
            }
        )
    return sections


def _records(
    args: argparse.Namespace, dataset: dict
) -> tuple[list[dict], dict, list[dict], list[dict]]:
    selectors = [
        parse_selector(specification)
        for group in dataset["topic_groups"]
        for specification in group["selectors"]
    ]
    books = sorted({selector["book"] for selector in selectors})
    passages, extraction_meta = extract_catalogue_passages(
        data_dir=args.data_dir, books_path=args.books_json, book_ids=books
    )
    records = [passage.to_dict() for passage in passages]
    chosen = select_records(records, selectors, dataset["max_passages"])
    return records, extraction_meta, selectors, chosen


def cmd_build(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    if Path(args.index).resolve() == default_index_dir().resolve():
        raise ValueError(
            "Refusing to overwrite the step 2b proof index; the evaluation index needs its own path"
        )

    dataset = load_dataset(args.dataset)
    records, extraction_meta, selectors, chosen = _records(args, dataset)
    if not chosen:
        raise ValueError("The declared selectors matched no passages")
    if len(chosen) > dataset["max_passages"]:
        raise ValueError(
            f"Selected {len(chosen)} passages, over the declared {dataset['max_passages']}"
        )

    selector_stats: list[dict] = []
    for group in dataset["topic_groups"]:
        for specification in group["selectors"]:
            selector = parse_selector(specification)
            selector_stats.append(
                {
                    "selector": specification,
                    "topic_group": group["id"],
                    "book_id": selector["book"],
                    "cap": selector["cap"],
                    "matched_before_cap": selector_match_count(records, selector),
                }
            )

    pool_sections = _sections(chosen)
    relevant_sections = resolve_relevant_sections(dataset, pool_sections)

    embedder = EmbeddingGemmaEmbedder(
        model_id=args.model, revision=args.revision or None, batch_size=args.batch_size
    )
    evaluation_meta = {
        "dataset_id": dataset["id"],
        "dataset_sha256": dataset["_sha256"],
        "dataset_path": dataset["_path"],
        "candidate_pool": {
            "max_passages": dataset["max_passages"],
            "candidate_passages": len(chosen),
            "extraction_passages": len(records),
            "books": sorted({record["book_id"] for record in chosen}),
            "grades": sorted({record["grade"] for record in chosen if record.get("grade")}),
            "topic_groups": [
                {"id": group["id"], "label": group["label"], "book_id": group["book_id"]}
                for group in dataset["topic_groups"]
            ],
            "selectors": selector_stats,
        },
    }
    index = build_index(
        chosen,
        embedder,
        corpus={"evaluation": evaluation_meta, "extraction": extraction_meta},
    )
    indexed_sections = {entry["section_id"] for entry in index.entries}
    unretrievable = {
        item_id: [
            section["section_id"]
            for section in sections
            if section["section_id"] not in indexed_sections
        ]
        for item_id, sections in relevant_sections.items()
    }
    unretrievable = {key: value for key, value in unretrievable.items() if value}
    if unretrievable:
        raise ValueError(
            "Declared relevant sections have no indexed passage: "
            + json.dumps(unretrievable, ensure_ascii=False)
        )
    evaluation_meta["candidate_pool"].update(
        {
            "indexed_passages": len(index.entries),
            "skipped_empty_text": index.skipped_empty_text,
            "incomplete_text_passages": sum(
                1 for entry in index.entries if not entry["text_complete"]
            ),
        }
    )
    index.corpus["evaluation"] = evaluation_meta
    index_path = save_index(index, Path(args.index))

    by_id = {record["id"]: record for record in chosen}
    baseline_records = []
    for entry in index.entries:
        record = by_id[entry["passage_id"]]
        baseline_records.append(
            {
                "passage_id": entry["passage_id"],
                "section_id": entry["section_id"],
                "book_id": entry["book_id"],
                "title": entry["title"],
                "text": record["text"],
                "text_complete": entry["text_complete"],
            }
        )
    corpus_path = save_baseline_corpus(index_path / CORPUS_FILE, baseline_records)

    queries = iter_queries(dataset)
    query_vectors = [embedder.encode_query(query["text"]) for query in queries]
    save_query_vectors(
        index_path,
        queries,
        query_vectors,
        dimension=index.dimension,
        meta={
            "dataset_id": dataset["id"],
            "dataset_sha256": dataset["_sha256"],
            "model_id": index.model_id,
            "model_revision": index.model_revision,
            "query_prefix": QUERY_PREFIX,
            "relevant_sections": relevant_sections,
        },
    )

    print(
        json.dumps(
            {
                "dataset": {
                    "id": dataset["id"],
                    "sha256": dataset["_sha256"],
                    "concepts": len(dataset["concepts"]),
                    "absent_topics": len(dataset["absent_topics"]),
                    "topic_groups": len(dataset["topic_groups"]),
                },
                "index": str(index_path),
                "baseline_corpus": str(corpus_path),
                "queries": str(index_path / QUERY_FILE),
                "model": embedder.describe(),
                "candidate_pool": evaluation_meta["candidate_pool"],
                "query_count": len(queries),
                "elapsed_seconds_one_run": round(time.perf_counter() - started, 2),
                "timing_note": "one build run including model load; not a benchmark",
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    index_path = Path(args.index)
    index = load_index(index_path)
    query_payload, queries, query_vectors = load_query_vectors(index_path)
    baseline_corpus = load_baseline_corpus(index_path / CORPUS_FILE)

    evaluation_meta = index.corpus.get("evaluation") or {}
    if query_payload.get("dataset_sha256") != evaluation_meta.get("dataset_sha256"):
        raise ValueError("Query metadata and index were built from different datasets")
    if query_payload.get("model_id") != index.model_id:
        raise ValueError("Query metadata and index name different models")
    if query_payload.get("model_revision") != index.model_revision:
        raise ValueError("Query metadata and index name different model revisions")
    index_ids = [entry["passage_id"] for entry in index.entries]
    corpus_ids = [record["passage_id"] for record in baseline_corpus]
    if index_ids != corpus_ids:
        raise ValueError("Baseline corpus does not match the saved index passages")
    if len(queries) != len(query_vectors):
        raise ValueError("Query metadata and saved vectors disagree")

    report = build_evaluation_report(
        index, baseline_corpus, query_payload, queries, query_vectors
    )
    report["artifacts"] = {
        "index": str(index_path),
        "queries": str(index_path / QUERY_FILE),
        "query_vectors": str(index_path / "query-vectors.f32"),
        "baseline_corpus": str(index_path / CORPUS_FILE),
    }
    if not args.details:
        report.pop("rows", None)
        report["rows_omitted"] = True

    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="embed the declared candidate pool and questions")
    build.add_argument("--index", type=Path, default=default_eval_index_dir())
    build.add_argument("--dataset", type=Path, default=default_dataset_path())
    build.add_argument("--model", default=MODEL_ID)
    build.add_argument(
        "--revision",
        default="",
        help="branch, tag, or commit hash; the resolved commit is recorded in the index",
    )
    build.add_argument("--batch-size", type=int, default=8)
    build.add_argument("--data-dir", type=Path, default=default_data_dir())
    build.add_argument("--books-json", type=Path, default=DEFAULT_BOOKS_PATH)
    build.set_defaults(func=cmd_build)

    report = sub.add_parser("report", help="rerank from saved vectors without loading a model")
    report.add_argument("--index", type=Path, default=default_eval_index_dir())
    report.add_argument(
        "--details",
        action="store_true",
        help="include every per-query row (the determinism digest always uses them)",
    )
    report.add_argument("--json", type=Path, default=None, help="also write the printed report")
    report.set_defaults(func=cmd_report)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, RuntimeError, KeyError, FileNotFoundError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
