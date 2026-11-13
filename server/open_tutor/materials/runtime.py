"""Process-lazy material search for the tutor tools (material-library step 4a).

This is the small adapter between the saved local index of step 2b/2c and the
agent tool that searches it. It adds no service, no endpoint and no database:

* The index comes from an **explicit** ``TUTOR_MATERIAL_INDEX`` directory. There
  is no fallback to a developer proof index: a host without that variable gets a
  clear "unavailable" result and ordinary tutoring stays untouched.
* The index and the embedding model are loaded lazily, once per process, and
  reused for every search. The model revision asked for is the exact revision
  recorded in the configured index, so cached weights cannot drift from the
  saved vectors.
* Loading and inference block (torch, disk, a possible HF cache check), so both
  run in a worker thread and never on the event loop.
* Results are reduced to **distinct source sections**: several high-scoring
  passages of one section become one candidate, carrying that section's best
  passage. Nothing per learner is stored here; the only shared mutable state is
  one inference lock for the shared weights.

The excerpts are passage text from the source book, which may include teacher
prose from the original EPUB. They are source text, not content the child can
see: only a later display step makes material visible, and feedback about what
is visible must come from the reviewed ``visible_text`` of that display.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import threading
from typing import Any, Sequence

from .search import (
    EmbeddingGemmaEmbedder,
    META_FILE,
    SearchIndex,
    load_index,
    query_index,
)

MATERIAL_INDEX_VAR = "TUTOR_MATERIAL_INDEX"
MAX_CANDIDATES = 5
# One query, not a document: bound what the model is asked to embed.
MAX_QUERY_CHARS = 500


class MaterialsUnavailable(RuntimeError):
    """Material search cannot run on this host; teaching continues in words."""


def configured_index_dir(environ: dict[str, str] | None = None) -> Path:
    """The index directory named by ``TUTOR_MATERIAL_INDEX``, or raise.

    Deliberately no default: an unset variable means this machine has no
    material library to search, not that some sample index should be used.
    """
    env = os.environ if environ is None else environ
    raw = (env.get(MATERIAL_INDEX_VAR) or "").strip()
    if not raw:
        raise MaterialsUnavailable(f"{MATERIAL_INDEX_VAR} is not configured")
    return Path(raw).expanduser()


def _embedding_model(model_id: str, revision: str) -> Any:
    """Load the real fp32 CPU text encoder at the index's own revision.

    Separate from :func:`load_runtime` so tests can supply a stub encoder
    without torch; the production path is the only caller in the server.
    """
    return EmbeddingGemmaEmbedder(model_id=model_id, revision=revision or None)


def section_candidates(
    ranked: Sequence[dict], limit: int = MAX_CANDIDATES
) -> list[dict]:
    """Reduce a passage ranking to one candidate per section, best passage first.

    ``ranked`` must already be ordered by score (``rank_index`` output). The
    first passage seen for a section is that section's best one, so the
    candidate carries its excerpt and scores. Scores order candidates only: a
    cosine between the query and one passage is not a confidence that the
    section answers the child's question.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    candidates: list[dict] = []
    seen: set[str] = set()
    for item in ranked:
        section_id = item["section_id"]
        if section_id in seen:
            continue
        if len(candidates) >= limit:
            break
        seen.add(section_id)
        candidates.append(
            {
                "rank": len(candidates) + 1,
                "section_id": section_id,
                "book_id": item.get("book_id") or "",
                "title": item.get("title") or "",
                "breadcrumbs": [str(part) for part in item.get("breadcrumbs") or []],
                "heading": item.get("heading") or "",
                "grade": item.get("grade"),
                "language": item.get("language") or "",
                "source_url": item.get("source_url") or "",
                "license": item.get("license") or "",
                "passage_id": item.get("passage_id") or "",
                "source_excerpt": item.get("excerpt") or "",
                "text_complete": bool(item.get("text_complete", False)),
                "image_count": len(item.get("images") or []),
                "score": item.get("score"),
            }
        )
    return candidates


class MaterialSearchRuntime:
    """One loaded index plus one model instance, both reused for this process."""

    def __init__(self, index: SearchIndex, embedder: Any, index_dir: Path) -> None:
        self.index = index
        self.embedder = embedder
        self.index_dir = Path(index_dir)
        # torch inference on shared weights: one search at a time, no per-learner state.
        self._inference_lock = threading.Lock()
        entries = index.entries
        self.section_count = len({entry["section_id"] for entry in entries})

    def summary(self) -> dict:
        """Coverage of the configured index.

        A saved index is always a selection of passages, never the whole library,
        so the tool reports its size rather than implying complete coverage.
        """
        books = sorted({entry.get("book_id") or "" for entry in self.index.entries} - {""})
        return {
            "passages": len(self.index.entries),
            "sections": self.section_count,
            "books": books,
        }

    def describe(self) -> dict:
        """Operational identity of the loaded runtime (for logs and verification)."""
        describe = getattr(self.embedder, "describe", None)
        model = describe() if callable(describe) else {
            "model_id": getattr(self.embedder, "model_id", ""),
            "model_revision": getattr(self.embedder, "model_revision", ""),
        }
        return {
            "index": str(self.index_dir),
            "index_model": {
                "model_id": self.index.model_id,
                "model_revision": self.index.model_revision,
                "dtype": self.index.dtype,
                "dimension": self.index.dimension,
            },
            "model": model,
            **self.summary(),
        }

    def search(self, query: str, limit: int = MAX_CANDIDATES) -> list[dict]:
        """Rank the whole index for one query and keep distinct sections."""
        with self._inference_lock:
            ranked = query_index(self.index, self.embedder, query, limit=None)
        return section_candidates(ranked, limit)


def load_runtime(index_dir: Path) -> MaterialSearchRuntime:
    """Read the saved index and load the model revision it recorded. Blocking."""
    directory = Path(index_dir)
    if not (directory / META_FILE).is_file():
        raise MaterialsUnavailable(
            f"{MATERIAL_INDEX_VAR} points at {directory}, which holds no {META_FILE}; "
            "configure a built index directory"
        )
    try:
        index = load_index(directory)
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        raise MaterialsUnavailable(
            f"The material index at {directory} could not be read: {error}"
        ) from error

    try:
        embedder = _embedding_model(index.model_id, index.model_revision)
    except ImportError as error:
        raise MaterialsUnavailable(
            "The optional ML dependencies for material search are not installed "
            f"(`uv sync --group ml`): {error}"
        ) from error
    except (OSError, ValueError, RuntimeError) as error:
        raise MaterialsUnavailable(
            f"The embedding model for the index at {directory} could not be loaded "
            f"({index.model_id}@{index.model_revision}): {error}"
        ) from error
    if getattr(embedder, "dtype", "") != "torch.float32":
        raise MaterialsUnavailable(
            "Material search needs float32 embeddings; the loaded encoder reports "
            f"{getattr(embedder, 'dtype', 'unknown')!r}"
        )
    return MaterialSearchRuntime(index, embedder, directory)


_STATE_LOCK = threading.Lock()
_runtime: MaterialSearchRuntime | None = None
_runtime_key: str | None = None


def runtime_for_process() -> MaterialSearchRuntime:
    """Load the configured runtime once per process (and once per index path)."""
    directory = configured_index_dir()
    key = str(directory)
    global _runtime, _runtime_key
    with _STATE_LOCK:
        if _runtime is not None and _runtime_key == key:
            return _runtime
        runtime = load_runtime(directory)
        _runtime, _runtime_key = runtime, key
        return runtime


def reset_runtime() -> None:
    """Forget the process runtime: tests, or an operator switching the index."""
    global _runtime, _runtime_key
    with _STATE_LOCK:
        _runtime, _runtime_key = None, None


async def search_material(query: str, limit: int = MAX_CANDIDATES) -> dict:
    """Search the configured index off the event loop and return tutor-facing data.

    Raises :class:`MaterialsUnavailable` when this host has no usable
    configuration; the tool caller decides what the tutor hears instead.
    """
    text = " ".join((query or "").split())[:MAX_QUERY_CHARS]
    if not text:
        raise ValueError("A search query is required")
    if limit <= 0:
        raise ValueError("limit must be positive")
    runtime = await asyncio.to_thread(runtime_for_process)
    candidates = await asyncio.to_thread(runtime.search, text, limit)
    return {
        "query": text,
        "index": runtime.summary(),
        "candidates": candidates,
    }


async def describe_material_search() -> dict:
    """Load (if needed) and describe the configured runtime. Blocking work is threaded."""
    runtime = await asyncio.to_thread(runtime_for_process)
    return runtime.describe()
