"""Rerunnable section-level retrieval evaluation for material-library step 2c.

This module holds the measurement code, not the production search path:

* a declared dataset (selectors, source-section labels, English and Swedish
  spoken-style questions) is loaded and checked before any ranking runs;
* both methods are compared on exactly the same candidate passages, one
  EmbeddingGemma 2 vector index and one stdlib BM25 lexical index;
* rankings are reduced to sections before scoring, so several passages from one
  section count once, never as several correct answers;
* a report can be rebuilt from saved passage and query vectors, with no model
  load and no EPUB read, and checks that two ranking passes agree.

Only the standard library is used here, so ordinary server tests do not need
torch. The real model is used only by the CLI's build command.
"""

from __future__ import annotations

from array import array
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Iterable, Sequence

from open_tutor.materials.search import SearchIndex, normalize, rank_index

DATASET_FORMAT = "open-tutor-retrieval-eval/1"
QUERY_FORMAT = "open-tutor-retrieval-eval-queries/1"
QUERY_FILE = "queries.json"
QUERY_VECTOR_FILE = "query-vectors.f32"
CORPUS_FILE = "baseline-corpus.json"
VECTOR_ENCODING = "float32-le"
TOP_K = 5
QUERY_LANGUAGES = ("en", "sv")
DATASET_PATH = Path(__file__).with_name("retrieval-eval-dataset.json")

# One tokenizer and one stopword list for English and Swedish queries. No
# stemming, dictionary or translation: a Swedish query's lexical overlap with
# the English corpus is reported instead of being invented.
TOKEN_PATTERN = re.compile(r"[0-9a-zà-öø-ÿ]+")
STOPWORDS = frozenset(
    "a an and are as at be because been but by can could did do does for from had has have "
    "how i if in into is it its of on or our so than that the their them then there these they "
    "this to was we were what when where which who why will with you your".split()
)


def default_dataset_path() -> Path:
    return DATASET_PATH


def dataset_digest(path: Path | None = None) -> str:
    """SHA-256 of the declared dataset file, so an artifact names its labels."""
    return hashlib.sha256(Path(path or DATASET_PATH).read_bytes()).hexdigest()


def load_dataset(path: Path | None = None) -> dict:
    """Load and structurally validate the declared evaluation dataset."""
    source = Path(path or DATASET_PATH)
    dataset = json.loads(source.read_text(encoding="utf-8"))
    if dataset.get("format") != DATASET_FORMAT:
        raise ValueError(f"Unsupported evaluation dataset format: {dataset.get('format')!r}")

    groups = dataset.get("topic_groups") or []
    if len(groups) < 6:
        raise ValueError("Evaluation dataset needs at least six topic groups")
    group_ids: set[str] = set()
    for group in groups:
        group_id = group.get("id") or ""
        if not group_id or group_id in group_ids:
            raise ValueError(f"Topic group id is missing or duplicated: {group_id!r}")
        group_ids.add(group_id)
        if not group.get("book_id"):
            raise ValueError(f"Topic group {group_id} has no book_id")
        if not group.get("selectors"):
            raise ValueError(f"Topic group {group_id} has no selectors")

    concepts = dataset.get("concepts") or []
    if len(concepts) < 12:
        raise ValueError("Evaluation dataset needs at least twelve concepts")
    concept_ids: set[str] = set()
    for concept in concepts:
        concept_id = concept.get("id") or ""
        if not concept_id or concept_id in concept_ids:
            raise ValueError(f"Concept id is missing or duplicated: {concept_id!r}")
        concept_ids.add(concept_id)
        if concept.get("topic_group") not in group_ids:
            raise ValueError(f"Concept {concept_id} names an unknown topic group")
        questions = concept.get("questions") or {}
        for language in QUERY_LANGUAGES:
            if not str(questions.get(language) or "").strip():
                raise ValueError(f"Concept {concept_id} has no {language} question")
        labels = concept.get("relevant_sections") or []
        if not labels:
            raise ValueError(f"Concept {concept_id} declares no relevant source section")
        for label in labels:
            if not label.get("book_id") or not str(label.get("heading") or "").strip():
                raise ValueError(f"Concept {concept_id} has an incomplete section label")

    absent = dataset.get("absent_topics") or []
    if not absent:
        raise ValueError("Evaluation dataset needs at least one absent-topic question")
    absent_ids: set[str] = set()
    for item in absent:
        item_id = item.get("id") or ""
        if not item_id or item_id in absent_ids:
            raise ValueError(f"Absent-topic id is missing or duplicated: {item_id!r}")
        absent_ids.add(item_id)
        questions = item.get("questions") or {}
        for language in QUERY_LANGUAGES:
            if not str(questions.get(language) or "").strip():
                raise ValueError(f"Absent topic {item_id} has no {language} question")
        if item.get("relevant_sections"):
            raise ValueError(f"Absent topic {item_id} must not declare relevant sections")

    dataset["_path"] = str(source)
    dataset["_sha256"] = dataset_digest(source)
    return dataset


def iter_queries(dataset: dict) -> list[dict]:
    """Every declared question as one query record, in a stable order."""
    queries: list[dict] = []
    for concept in dataset["concepts"]:
        for language in QUERY_LANGUAGES:
            queries.append(
                {
                    "query_id": f"{concept['id']}:{language}",
                    "item_id": concept["id"],
                    "kind": "concept",
                    "topic_group": concept["topic_group"],
                    "language": language,
                    "text": concept["questions"][language],
                }
            )
    for absent in dataset["absent_topics"]:
        for language in QUERY_LANGUAGES:
            queries.append(
                {
                    "query_id": f"{absent['id']}:{language}",
                    "item_id": absent["id"],
                    "kind": "absent",
                    "topic_group": "absent",
                    "language": language,
                    "text": absent["questions"][language],
                }
            )
    ids = [query["query_id"] for query in queries]
    if len(set(ids)) != len(ids):
        raise ValueError("Declared query ids are not unique")
    return queries


def section_key(section: dict) -> tuple[str, tuple[str, ...], str]:
    """Human-stable section identity used by the declared labels."""
    return (
        section.get("book_id", ""),
        tuple(str(part) for part in section.get("breadcrumbs") or []),
        str(section.get("heading") or ""),
    )


def _title(parts: Iterable[str]) -> str:
    seen: list[str] = []
    for part in parts:
        text = " ".join(str(part).split())
        if text and (not seen or seen[-1] != text):
            seen.append(text)
    return " > ".join(seen)


def resolve_relevant_sections(dataset: dict, sections: Sequence[dict]) -> dict[str, list[dict]]:
    """Resolve declared labels to the concrete sections in the candidate pool.

    A label matches exactly one section by book, breadcrumbs and heading. A
    missing or ambiguous label is an error: an evaluation must not silently
    score against a section that is not in the pool.
    """
    lookup: dict[tuple[str, tuple[str, ...], str], list[dict]] = {}
    for section in sections:
        lookup.setdefault(section_key(section), []).append(section)

    ambiguous = {
        key: values for key, values in lookup.items() if len({item["section_id"] for item in values}) > 1
    }
    if ambiguous:
        detail = "; ".join(f"{key[0]} / {' > '.join([*key[1], key[2]])}" for key in list(ambiguous)[:5])
        raise ValueError(f"Declared section identity is ambiguous: {detail}")

    resolved: dict[str, list[dict]] = {}
    missing: list[str] = []
    for concept in dataset["concepts"]:
        chosen: list[dict] = []
        seen: set[str] = set()
        for label in concept["relevant_sections"]:
            key = section_key(label)
            matches = lookup.get(key)
            if not matches:
                missing.append(
                    f"{concept['id']}: {key[0]} / {' > '.join([*key[1], key[2]])}"
                )
                continue
            match = matches[0]
            if match["section_id"] not in seen:
                seen.add(match["section_id"])
                chosen.append(
                    {
                        "section_id": match["section_id"],
                        "book_id": match["book_id"],
                        "title": _title([*key[1], key[2]]),
                    }
                )
        if not chosen and not any(item.startswith(concept["id"] + ":") for item in missing):
            raise ValueError(f"Concept {concept['id']} has no resolvable section")
        resolved[concept["id"]] = chosen
    if missing:
        raise ValueError(
            "Declared relevant sections are not in the candidate pool: " + "; ".join(missing[:10])
        )
    return resolved


def tokenize(text: str) -> list[str]:
    """Lower-case tokens with one stopword list for every query language."""
    return [token for token in TOKEN_PATTERN.findall(text.casefold()) if token not in STOPWORDS]


@dataclass
class LexicalIndex:
    """Small stdlib BM25 baseline over the same passage set as the vector index."""

    documents: list[dict] = field(default_factory=list)
    term_frequencies: list[Counter] = field(default_factory=list)
    lengths: list[int] = field(default_factory=list)
    document_frequency: Counter = field(default_factory=Counter)
    average_length: float = 0.0
    k1: float = 1.2
    b: float = 0.75

    @classmethod
    def from_records(cls, records: Sequence[dict]) -> "LexicalIndex":
        documents: list[dict] = []
        term_frequencies: list[Counter] = []
        lengths: list[int] = []
        document_frequency: Counter = Counter()
        for record in records:
            title = record.get("title") or record.get("heading") or ""
            text = f"{title}. {record.get('text') or ''}"
            tokens = tokenize(text)
            frequencies = Counter(tokens)
            term_frequencies.append(frequencies)
            lengths.append(len(tokens))
            document_frequency.update(frequencies.keys())
            documents.append(
                {
                    "passage_id": record.get("passage_id") or record["id"],
                    "section_id": record["section_id"],
                    "book_id": record.get("book_id", ""),
                    "title": title,
                    "text_complete": bool(record.get("text_complete", False)),
                }
            )
        average = sum(lengths) / len(lengths) if lengths else 0.0
        return cls(
            documents=documents,
            term_frequencies=term_frequencies,
            lengths=lengths,
            document_frequency=document_frequency,
            average_length=average,
        )

    def overlap(self, query: str) -> dict:
        terms = sorted({token for token in tokenize(query)})
        matched = [term for term in terms if self.document_frequency.get(term, 0) > 0]
        return {
            "query_terms": len(terms),
            "matched_terms": matched,
            "matched_count": len(matched),
            "zero_overlap": not matched,
        }

    def search(self, query: str) -> list[dict]:
        """Rank all passages; ties keep corpus order, so the run is repeatable."""
        terms = sorted({token for token in tokenize(query)})
        total = len(self.documents)
        scores: list[float] = []
        for position, frequencies in enumerate(self.term_frequencies):
            length = self.lengths[position]
            score = 0.0
            for term in terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                df = self.document_frequency[term]
                idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
                denominator = frequency + self.k1 * (
                    1 - self.b + self.b * (length / self.average_length if self.average_length else 0)
                )
                score += idf * (frequency * (self.k1 + 1) / denominator)
            scores.append(score)

        order = sorted(range(total), key=lambda position: (-scores[position], position))
        results: list[dict] = []
        for rank, position in enumerate(order, start=1):
            results.append(
                {**self.documents[position], "rank": rank, "score": round(scores[position], 6)}
            )
        return results


def section_ranking(results: Sequence[dict]) -> list[dict]:
    """Collapse a passage ranking to sections, keeping the best passage first.

    Several passages from one section become one section entry, so a section is
    counted once whether it contributes one passage or ten.
    """
    sections: list[dict] = []
    positions: dict[str, int] = {}
    for result in results:
        section_id = result["section_id"]
        if section_id not in positions:
            positions[section_id] = len(sections)
            sections.append(
                {
                    "section_id": section_id,
                    "book_id": result.get("book_id", ""),
                    "title": result.get("title", ""),
                    "first_rank": result["rank"],
                    "best_score": result["score"],
                    "passage_ids": [result["passage_id"]],
                    "text_complete": bool(result.get("text_complete", False)),
                    "any_text_complete": bool(result.get("text_complete", False)),
                }
            )
            continue
        entry = sections[positions[section_id]]
        entry["passage_ids"].append(result["passage_id"])
        entry["any_text_complete"] = entry["any_text_complete"] or bool(
            result.get("text_complete", False)
        )
    return sections


def _section_view(section: dict, relevant_ids: set[str], scored: bool) -> dict:
    return {
        "section_id": section["section_id"],
        "book_id": section["book_id"],
        "title": section["title"],
        "first_rank": section["first_rank"],
        "best_score": section["best_score"],
        "text_complete": section["text_complete"],
        "any_text_complete": section["any_text_complete"],
        "passage_count": len(section["passage_ids"]),
        "relevant": (section["section_id"] in relevant_ids) if scored else None,
    }


def evaluate_sections(
    ranked_sections: Sequence[dict],
    relevant_ids: set[str],
    k: int = TOP_K,
    passage_results: Sequence[dict] | None = None,
) -> dict:
    """Section-level top-1/top-k result for one query.

    ``passage_results`` is the uncollapsed ranking. When given, it records how
    many of the first k *passage* results were further passages from a section
    already seen, which is exactly the overcount that section-level scoring
    avoids.
    """
    scored = bool(relevant_ids)
    top = ranked_sections[:k]
    hit_rank = None
    if scored:
        hit_rank = next(
            (
                position
                for position, section in enumerate(ranked_sections, start=1)
                if section["section_id"] in relevant_ids
            ),
            None,
        )
    duplicate_passage_sections = None
    if passage_results is not None:
        seen_sections: set[str] = set()
        duplicate_passage_sections = 0
        for result in passage_results[:k]:
            if result["section_id"] in seen_sections:
                duplicate_passage_sections += 1
            seen_sections.add(result["section_id"])
    return {
        "scored": scored,
        "top1": (top[0]["section_id"] in relevant_ids) if scored and top else None,
        "top5": (hit_rank is not None and hit_rank <= k) if scored else None,
        "hit_section_rank": hit_rank,
        "top1_section": _section_view(top[0], relevant_ids, scored) if top else None,
        "top5_sections": [
            {**_section_view(section, relevant_ids, scored), "section_rank": position}
            for position, section in enumerate(top, start=1)
        ],
        "passage_level_duplicate_sections_in_top5": duplicate_passage_sections,
    }


def _rate(count: int, total: int) -> dict:
    return {"count": count, "total": total, "rate": round(count / total, 4) if total else None}


def summarize(rows: Sequence[dict]) -> dict:
    """Counts for the declared-label rows; absent-topic rows are excluded."""
    scored = [row for row in rows if row["scored"]]
    total = len(scored)
    top1 = sum(1 for row in scored if row["top1"])
    top5 = sum(1 for row in scored if row["top5"])
    top1_incomplete = sum(
        1 for row in scored if row["top1_section"] and not row["top1_section"]["text_complete"]
    )
    top1_hits_incomplete = sum(
        1
        for row in scored
        if row["top1"] and row["top1_section"] and not row["top1_section"]["text_complete"]
    )
    no_hit = sum(1 for row in scored if row["hit_section_rank"] is None)
    return {
        "scored_queries": total,
        "top1": _rate(top1, total),
        "top5_sections": _rate(top5, total),
        "top1_sections_with_incomplete_text": _rate(top1_incomplete, total),
        "top1_hits_with_incomplete_text": _rate(top1_hits_incomplete, top1),
        "no_relevant_section_in_top5": _rate(no_hit, total),
        "passage_level_duplicate_sections_in_top5": sum(
            row["passage_level_duplicate_sections_in_top5"] or 0 for row in scored
        ),
    }


def _group_summary(rows: Sequence[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        if row["scored"]:
            groups.setdefault(str(row[key]), []).append(row)
    return {name: summarize(values) for name, values in sorted(groups.items())}


def _evaluation_row(
    query: dict,
    evaluation: dict,
    relevant_sections: Sequence[dict],
    extra: dict | None = None,
) -> dict:
    row = {
        "query_id": query["query_id"],
        "item_id": query["item_id"],
        "kind": query["kind"],
        "topic_group": query["topic_group"],
        "language": query["language"],
        "text": query["text"],
        "relevant_sections": [dict(section) for section in relevant_sections],
        **evaluation,
    }
    if extra:
        row.update(extra)
    return row


def save_query_vectors(
    path: Path,
    queries: Sequence[dict],
    vectors: Sequence[Sequence[float]],
    *,
    dimension: int,
    meta: dict,
) -> Path:
    """Save normalized query vectors and their declared metadata outside Git."""
    if len(queries) != len(vectors):
        raise ValueError(f"Got {len(vectors)} vectors for {len(queries)} queries")
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    flat = array("f")
    for query, vector in zip(queries, vectors):
        values = [float(value) for value in vector]
        if len(values) != dimension:
            raise ValueError(
                f"Query {query['query_id']} has {len(values)} values, expected {dimension}"
            )
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"Query {query['query_id']} has non-finite values")
        flat.extend(normalize(values))
    if sys.byteorder != "little":
        flat.byteswap()
    (path / QUERY_VECTOR_FILE).write_bytes(flat.tobytes())
    payload = {
        **meta,
        "format": QUERY_FORMAT,
        "vectors": {
            "file": QUERY_VECTOR_FILE,
            "encoding": VECTOR_ENCODING,
            "count": len(queries),
            "dimension": dimension,
        },
        "queries": [dict(query) for query in queries],
    }
    (path / QUERY_FILE).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def load_query_vectors(path: Path) -> tuple[dict, list[dict], list[array]]:
    """Read saved query vectors; no model and no EPUB needed."""
    path = Path(path)
    payload = json.loads((path / QUERY_FILE).read_text(encoding="utf-8"))
    if payload.get("format") != QUERY_FORMAT:
        raise ValueError(f"Unsupported query metadata format: {payload.get('format')!r}")
    dimensions = payload["vectors"]
    dimension = int(dimensions["dimension"])
    count = int(dimensions["count"])
    queries = list(payload["queries"])
    if len(queries) != count:
        raise ValueError(f"Query metadata says {count} queries, found {len(queries)}")
    flat = array("f")
    flat.frombytes((path / QUERY_VECTOR_FILE).read_bytes())
    if sys.byteorder != "little":
        flat.byteswap()
    if len(flat) != count * dimension:
        raise ValueError(
            f"Query vector file holds {len(flat)} values, expected {count * dimension}"
        )
    vectors = [flat[index * dimension : (index + 1) * dimension] for index in range(count)]
    return payload, queries, vectors


def save_baseline_corpus(path: Path, records: Sequence[dict]) -> Path:
    """Write the passage text the lexical baseline ranks, outside Git."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = [record["passage_id"] for record in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Baseline corpus contains duplicate passage ids")
    path.write_text(
        json.dumps(list(records), ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def load_baseline_corpus(path: Path) -> list[dict]:
    path = Path(path)
    records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Baseline corpus is not a list of passage records")
    return records


def _rows_for(
    index: SearchIndex,
    lexical: LexicalIndex,
    query_payload: dict,
    queries: Sequence[dict],
    query_vectors: Sequence[Sequence[float]],
    *,
    embedding: bool,
) -> list[dict]:
    relevant_by_item = query_payload.get("relevant_sections") or {}
    rows: list[dict] = []
    for query, vector in zip(queries, query_vectors):
        relevant_sections = (
            relevant_by_item.get(query["item_id"], []) if query["kind"] == "concept" else []
        )
        relevant_ids = {section["section_id"] for section in relevant_sections}
        if embedding:
            raw = rank_index(index, vector)
            extra = None
        else:
            raw = lexical.search(query["text"])
            extra = {"lexical_overlap": lexical.overlap(query["text"])}
        evaluation = evaluate_sections(
            section_ranking(raw), relevant_ids, passage_results=raw
        )
        rows.append(_evaluation_row(query, evaluation, relevant_sections, extra))
    return rows


def _compact_result(row: dict) -> dict:
    return {
        "query_id": row["query_id"],
        "text": row["text"],
        "language": row["language"],
        "relevant_sections": row["relevant_sections"],
        "hit_section_rank": row["hit_section_rank"],
        "top1_section": row["top1_section"],
        "top5_sections": row["top5_sections"],
    }


def collect_misses(rows: Sequence[dict]) -> dict:
    scored = [row for row in rows if row["scored"]]
    top1_misses = [row for row in scored if not row["top1"]]
    top5_misses = [row for row in scored if not row["top5"]]
    return {
        "top1_miss_count": len(top1_misses),
        "top5_miss_count": len(top5_misses),
        "top1_misses": [_compact_result(row) for row in top1_misses],
        "top5_misses": [_compact_result(row) for row in top5_misses],
    }


def summarize_absent(rows: Sequence[dict]) -> dict:
    absent = [row for row in rows if row["kind"] == "absent"]
    scores = [
        row["top1_section"]["best_score"]
        for row in absent
        if row["top1_section"] is not None
    ]
    return {
        "queries": len(absent),
        "top1_scores": {
            "min": round(min(scores), 4) if scores else None,
            "max": round(max(scores), 4) if scores else None,
            "mean": round(sum(scores) / len(scores), 4) if scores else None,
        },
        "rows": [
            {
                "query_id": row["query_id"],
                "text": row["text"],
                "language": row["language"],
                "top1_section": row["top1_section"],
                "top5_sections": row["top5_sections"],
            }
            for row in absent
        ],
        "note": "No declared relevant section exists for these questions, so no top-1/top-5 accuracy is computed.",
    }


def _language_treatment(lexical_rows: Sequence[dict]) -> dict:
    by_language: dict[str, dict] = {}
    for language in QUERY_LANGUAGES:
        rows = [row for row in lexical_rows if row["language"] == language]
        overlaps = [row["lexical_overlap"] for row in rows]
        by_language[language] = {
            "queries": len(rows),
            "queries_with_zero_lexical_overlap": sum(1 for item in overlaps if item["zero_overlap"]),
            "total_matched_terms": sum(item["matched_count"] for item in overlaps),
            "mean_matched_terms": round(
                sum(item["matched_count"] for item in overlaps) / len(overlaps), 3
            )
            if overlaps
            else None,
        }
    return {
        "corpus_language": "en",
        "query_languages": list(QUERY_LANGUAGES),
        "translation": "none",
        "embedding": "Swedish query text is embedded unchanged with the same SearchQuery prompt; documents use the English title/text prompt.",
        "lexical": "The same tokenizer and stopword list are used for both query languages, with no stemming, dictionary or translation. Query-term overlap with the English corpus is reported per query.",
        "lexical_overlap_by_language": by_language,
    }


def _incomplete_analysis(
    index: SearchIndex,
    relevant_by_item: dict,
    rows_by_method: dict,
) -> dict:
    entries = index.entries
    section_complete: dict[str, bool] = {}
    by_book: dict[str, dict] = {}
    for entry in entries:
        book = entry.get("book_id", "")
        stats = by_book.setdefault(book, {"passages": 0, "incomplete": 0})
        stats["passages"] += 1
        if not entry["text_complete"]:
            stats["incomplete"] += 1
        section_complete[entry["section_id"]] = section_complete.get(
            entry["section_id"], False
        ) or bool(entry["text_complete"])

    relevant: dict[str, dict] = {}
    for item_id, sections in relevant_by_item.items():
        ids = [section["section_id"] for section in sections]
        passages = [entry for entry in entries if entry["section_id"] in ids]
        relevant[item_id] = {
            "passages": len(passages),
            "complete_passages": sum(1 for entry in passages if entry["text_complete"]),
            "all_passages_incomplete": bool(passages)
            and not any(entry["text_complete"] for entry in passages),
            "sections_without_complete_text": [
                section_id for section_id in ids if not section_complete.get(section_id, False)
            ],
        }

    per_method: dict[str, dict] = {}
    for method, rows in rows_by_method.items():
        scored = [row for row in rows if row["scored"]]
        per_method[method] = {
            "top1_sections_with_incomplete_text": sum(
                1
                for row in scored
                if row["top1_section"] and not row["top1_section"]["text_complete"]
            ),
            "top1_hits_with_incomplete_text": sum(
                1
                for row in scored
                if row["top1"]
                and row["top1_section"]
                and not row["top1_section"]["text_complete"]
            ),
            "top1_any_complete": sum(
                1
                for row in scored
                if row["top1_section"] and row["top1_section"]["any_text_complete"]
            ),
        }

    return {
        "pool": {
            "passages": len(entries),
            "incomplete_text_passages": sum(1 for entry in entries if not entry["text_complete"]),
            "incomplete_fraction": round(
                sum(1 for entry in entries if not entry["text_complete"]) / len(entries), 4
            )
            if entries
            else None,
        },
        "by_book": by_book,
        "relevant_sections": relevant,
        "concepts_with_only_incomplete_relevant_text": sorted(
            item_id
            for item_id, stats in relevant.items()
            if stats["all_passages_incomplete"]
        ),
        "by_method": per_method,
        "note": "A text_complete=false passage has at least one image; mathematical expressions are often PNGs without alt text, so correct retrieval can still return incomplete teaching text.",
    }


def build_evaluation_report(
    index: SearchIndex,
    baseline_corpus: Sequence[dict],
    query_payload: dict,
    queries: Sequence[dict],
    query_vectors: Sequence[Sequence[float]],
) -> dict:
    """Build the full report from saved vectors and saved passage text."""
    lexical = LexicalIndex.from_records(baseline_corpus)
    embedding_rows = _rows_for(
        index, lexical, query_payload, queries, query_vectors, embedding=True
    )
    lexical_rows = _rows_for(
        index, lexical, query_payload, queries, query_vectors, embedding=False
    )
    embedding_again = _rows_for(
        index, lexical, query_payload, queries, query_vectors, embedding=True
    )
    lexical_again = _rows_for(
        index, lexical, query_payload, queries, query_vectors, embedding=False
    )
    first = {"embeddinggemma": embedding_rows, "lexical_bm25": lexical_rows}
    second = {"embeddinggemma": embedding_again, "lexical_bm25": lexical_again}
    digest = hashlib.sha256(
        json.dumps(first, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()

    relevant_by_item = query_payload.get("relevant_sections") or {}
    methods = {}
    for name, rows in first.items():
        methods[name] = {
            "overall": summarize(rows),
            "by_language": _group_summary(rows, "language"),
            "by_topic_group": _group_summary(rows, "topic_group"),
            "misses": collect_misses(rows),
        }

    evaluation_meta = index.corpus.get("evaluation") or {}
    return {
        "evaluation": {
            "dataset_id": evaluation_meta.get("dataset_id", ""),
            "dataset_sha256": evaluation_meta.get("dataset_sha256", ""),
            "dataset_path": evaluation_meta.get("dataset_path", ""),
            "index_corpus": evaluation_meta,
        },
        "model": {
            "model_id": index.model_id,
            "model_revision": index.model_revision,
            "dtype": index.dtype,
            "dimension": index.dimension,
        },
        "candidate_pool": evaluation_meta.get("candidate_pool", {}),
        "language_treatment": _language_treatment(lexical_rows),
        "methods": methods,
        "absent_topics": {
            "embeddinggemma": summarize_absent(embedding_rows),
            "lexical_bm25": summarize_absent(lexical_rows),
        },
        "image_incomplete": _incomplete_analysis(index, relevant_by_item, first),
        "determinism": {
            "runs": 2,
            "identical": first == second,
            "sha256": digest,
            "note": "Two ranking passes over the same saved passage and query vectors; no model call and no EPUB read in the report command.",
        },
        "rows": {
            "embeddinggemma": embedding_rows,
            "lexical_bm25": lexical_rows,
        },
    }
