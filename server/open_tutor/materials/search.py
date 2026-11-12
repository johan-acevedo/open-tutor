"""Bounded text search over extracted source passages (material-library step 2b).

An exact (brute-force cosine) vector index over a small passage sample, with the
model identity stored next to the vectors. This proves real EmbeddingGemma 2
retrieval on the source passages; it is not the production search API and it
does no approximate-nearest-neighbour or database work.

Two invariants the rest of the library depends on:

* Only a passage's *owned text* plus its heading and breadcrumb context is sent
  to the model. ``html`` and ``block_range`` may include bytes of neighbouring
  sections (the reviewed extraction says so explicitly), so they are never used
  as model input.
* A passage without owned text is skipped and counted, never embedded as an
  empty string. A passage whose content is partly images stays in the index with
  ``text_complete: false`` so a caller can say that flattened text is incomplete
  instead of presenting it as a whole worked example.

The module uses only the standard library, so ordinary server tests run without
torch or a model download. :class:`EmbeddingGemmaEmbedder` imports
sentence-transformers lazily and loads the text backbone only.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
import json
import math
import os
from pathlib import Path
import sys
from typing import Protocol, Sequence

MODEL_ID = "google/embeddinggemma-2"

# Official task instructions for asymmetric web/document search. The query side
# is also registered on the model as ``SearchQuery``; the document side is
# written by :func:`document_input` so the real title travels with the text.
QUERY_PREFIX = "task: search result | query: "
UNTITLED_DOCUMENT_PREFIX = "title: none | text: "

INDEX_FORMAT = "open-tutor-embedding-index/1"
META_FILE = "index.json"
VECTOR_FILE = "vectors.f32"
VECTOR_ENCODING = "float32-le"

# 768 numbers is the native EmbeddingGemma 2 output; float16 is unsafe for it
# (the activation range exceeds float16's, and the result is NaN or silently
# degraded rather than an error).
SUPPORTED_DTYPES = ("torch.float32", "torch.bfloat16")

EXCERPT_CHARS = 320


def default_index_dir() -> Path:
    """Index location outside Git, honouring XDG like the corpus directory."""
    base = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(base) / "open-tutor" / "materials" / "embeddinggemma-2-index"


def document_title(record: dict) -> str:
    """Human title of a passage record: breadcrumb path plus the innermost heading."""
    parts: list[str] = []
    for part in [*(record.get("breadcrumbs") or []), record.get("heading") or ""]:
        text = " ".join(str(part).split())
        if text and (not parts or parts[-1] != text):
            parts.append(text)
    return " > ".join(parts)


def document_input(record: dict) -> str:
    """Text actually embedded for a passage: title prefix plus owned text only."""
    text = record.get("text") or ""
    title = document_title(record)
    if title:
        return f"title: {title} | text: {text}"
    return UNTITLED_DOCUMENT_PREFIX + text


def normalize(values: Sequence[float]) -> list[float]:
    """Unit-length copy of a vector, so a dot product is a cosine similarity."""
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or norm == 0.0:
        raise ValueError("Cannot normalize a zero or non-finite vector")
    return [value / norm for value in values]


def _check_vector(values: Sequence[float], dimension: int, what: str) -> None:
    if len(values) != dimension:
        raise ValueError(f"{what} has {len(values)} values, expected {dimension}")
    if not all(math.isfinite(value) for value in values):
        raise ValueError(f"{what} contains non-finite values")


def ensure_supported_dtype(dtype: str) -> None:
    """Reject float16 (and unknown) precisions before they produce quiet garbage."""
    if dtype not in SUPPORTED_DTYPES:
        raise RuntimeError(
            f"EmbeddingGemma 2 needs float32 or bfloat16, got {dtype!r}. float16 gives NaN "
            "or silently degraded embeddings instead of an error."
        )


class TextEmbedder(Protocol):
    """What :func:`build_index` and :func:`query_index` need from an encoder."""

    model_id: str
    model_revision: str
    dtype: str
    dimension: int

    def encode_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...

    def encode_query(self, text: str) -> Sequence[float]: ...


class EmbeddingGemmaEmbedder:
    """Real EmbeddingGemma 2 text encoder: text-only, float32, on this CPU.

    The vision and audio encoders are not loaded (they are separate modules on
    the same checkpoint), and no task prompt is applied except the documented
    text prefixes.
    """

    def __init__(self, model_id: str = MODEL_ID, device: str = "cpu", batch_size: int = 8):
        import torch  # noqa: PLC0415 - optional ML dependency, never imported by the server
        from huggingface_hub import snapshot_download  # noqa: PLC0415
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        snapshot = Path(snapshot_download(model_id))
        self.model_id = model_id
        self.model_revision = snapshot.name  # resolved commit directory in the HF cache
        self.model = SentenceTransformer(
            str(snapshot),
            device=device,
            model_kwargs={"torch_dtype": torch.float32},
            config_kwargs={"vision_config": None, "audio_config": None},
        )
        self.dtype = str(self.model.dtype)
        ensure_supported_dtype(self.dtype)
        if self.model.prompts.get("SearchQuery") != QUERY_PREFIX:
            raise RuntimeError(
                "Model's SearchQuery prompt differs from the documented one: "
                f"{self.model.prompts.get('SearchQuery')!r}"
            )
        self.dimension = int(self.model.get_embedding_dimension())
        self.batch_size = batch_size

    def describe(self) -> dict:
        return {
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "dtype": self.dtype,
            "dimension": self.dimension,
            "encoders_loaded": "text only (vision_config=None, audio_config=None)",
            "device": str(self.model.device),
        }

    def encode_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if not texts:
            return []
        vectors = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def encode_query(self, text: str) -> Sequence[float]:
        vector = self.model.encode(
            text,
            prompt=QUERY_PREFIX,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vector.tolist()


def _excerpt(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= EXCERPT_CHARS:
        return flat
    cut = flat[:EXCERPT_CHARS].rsplit(" ", 1)[0]
    return cut + "…"


def _entry(record: dict) -> dict:
    """Index metadata for one passage: identity, source, and honest completeness."""
    images = [dict(image) for image in record.get("images") or []]
    return {
        "passage_id": record["id"],
        "section_id": record["section_id"],
        "book_id": record.get("book_id", ""),
        "title": document_title(record),
        "heading": record.get("heading", ""),
        "breadcrumbs": [str(part) for part in record.get("breadcrumbs") or []],
        "grade": record.get("grade"),
        "language": record.get("language", ""),
        "source_url": record.get("source_url", ""),
        "license": record.get("license", ""),
        "document_href": record.get("document_href", ""),
        "fragment": record.get("fragment", ""),
        "ordinal": record.get("ordinal"),
        "block_range": list(record.get("block_range") or []),
        "text_complete": bool(record.get("text_complete", not images)),
        "images": images,
        "characters": len(record.get("text") or ""),
        "excerpt": _excerpt(record.get("text") or ""),
    }


@dataclass
class SearchIndex:
    """Vectors plus the metadata needed to cite and to trust a result."""

    model_id: str
    model_revision: str
    dtype: str
    dimension: int
    entries: list[dict]
    vectors: array  # flat little-endian float32, one unit vector per entry
    corpus: dict = field(default_factory=dict)
    skipped_empty_text: int = 0

    def vector(self, position: int) -> array:
        start = position * self.dimension
        return self.vectors[start : start + self.dimension]

    def to_meta(self) -> dict:
        return {
            "format": INDEX_FORMAT,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "dtype": self.dtype,
            "query_prefix": QUERY_PREFIX,
            "document_prefix": "title: {title} | text: {content}",
            "vectors": {
                "file": VECTOR_FILE,
                "encoding": VECTOR_ENCODING,
                "count": len(self.entries),
                "dimension": self.dimension,
            },
            "corpus": self.corpus,
            "skipped_empty_text": self.skipped_empty_text,
            "entries": self.entries,
        }


def build_index(
    records: Sequence[dict], embedder: TextEmbedder, corpus: dict | None = None
) -> SearchIndex:
    """Embed the records that have owned text and return the exact index."""
    kept: list[dict] = []
    skipped = 0
    for record in records:
        if not (record.get("text") or "").strip():
            skipped += 1  # images-only or empty section: nothing honest to embed
            continue
        kept.append(record)
    if not kept:
        raise ValueError("No passages with text to embed")

    vectors = embedder.encode_documents([document_input(record) for record in kept])
    if len(vectors) != len(kept):
        raise ValueError(f"Embedder returned {len(vectors)} vectors for {len(kept)} passages")

    flat = array("f")
    for record, vector in zip(kept, vectors):
        values = [float(value) for value in vector]
        _check_vector(values, int(embedder.dimension), f"Embedding of {record['id']}")
        flat.extend(normalize(values))
    if sys.byteorder != "little":
        flat.byteswap()

    return SearchIndex(
        model_id=embedder.model_id,
        model_revision=embedder.model_revision,
        dtype=embedder.dtype,
        dimension=int(embedder.dimension),
        entries=[_entry(record) for record in kept],
        vectors=flat,
        corpus=dict(corpus or {}),
        skipped_empty_text=skipped,
    )


def query_index(
    index: SearchIndex, embedder: TextEmbedder, query: str, limit: int = 5
) -> list[dict]:
    """Rank passages against one query; raises if the index came from another model."""
    if index.model_id != embedder.model_id or index.model_revision != embedder.model_revision:
        raise ValueError(
            "Index was built with "
            f"{index.model_id}@{index.model_revision}, but the loaded model is "
            f"{embedder.model_id}@{embedder.model_revision}; rebuild the index"
        )
    if limit <= 0:
        raise ValueError("limit must be positive")
    query_vector = [float(value) for value in embedder.encode_query(query)]
    _check_vector(query_vector, index.dimension, "Query embedding")
    cosine = normalize(query_vector)

    scored: list[tuple[float, int]] = []
    for position in range(len(index.entries)):
        vector = index.vector(position)
        scored.append((sum(a * b for a, b in zip(cosine, vector)), position))
    scored.sort(key=lambda item: (-item[0], item[1]))

    results: list[dict] = []
    for rank, (score, position) in enumerate(scored[:limit], start=1):
        results.append({**index.entries[position], "rank": rank, "score": round(score, 6)})
    return results


def save_index(index: SearchIndex, path: Path) -> Path:
    """Write ``index.json`` and the raw vectors into ``path``."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    (path / VECTOR_FILE).write_bytes(index.vectors.tobytes())
    meta = index.to_meta()
    (path / META_FILE).write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def load_index(path: Path) -> SearchIndex:
    """Read an index written by :func:`save_index` and check its vectors."""
    path = Path(path)
    meta = json.loads((path / META_FILE).read_text(encoding="utf-8"))
    if meta.get("format") != INDEX_FORMAT:
        raise ValueError(f"Unsupported index format: {meta.get('format')!r}")
    if meta.get("dtype") not in SUPPORTED_DTYPES:
        raise RuntimeError(f"Index was built in unsupported precision {meta.get('dtype')!r}")
    layout = meta["vectors"]
    dimension = int(layout["dimension"])
    count = int(layout["count"])
    vectors = array("f")
    vectors.frombytes((path / VECTOR_FILE).read_bytes())
    if sys.byteorder != "little":
        vectors.byteswap()
    if len(vectors) != count * dimension:
        raise ValueError(
            f"Vector file holds {len(vectors)} values, expected {count * dimension}"
        )
    return SearchIndex(
        model_id=meta["model_id"],
        model_revision=meta["model_revision"],
        dtype=meta["dtype"],
        dimension=dimension,
        entries=list(meta["entries"]),
        vectors=vectors,
        corpus=dict(meta.get("corpus") or {}),
        skipped_empty_text=int(meta.get("skipped_empty_text", 0)),
    )
