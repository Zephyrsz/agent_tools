"""Application workflows spanning importers and persistent storage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .importers import ExtractedBatch, load_extracted_batch
from .repository import PostRepository


def ingest_batch(
    store: PostRepository,
    batch: ExtractedBatch,
    *,
    mode: str = "incremental",
    relation: str = "own_post",
) -> dict[str, Any]:
    run_id = store.begin_crawl(batch.handle, mode=mode, started_at=batch.captured_at)
    counts = store.upsert_posts(
        batch.posts,
        handle=batch.handle,
        captured_at=batch.captured_at,
        relation=relation,
    )
    store.finish_crawl(
        run_id,
        fetched_count=counts["fetched"],
        inserted_count=counts["inserted"],
        updated_count=counts["updated"],
        unchanged_count=counts["unchanged"],
        skipped_count=counts["skipped"],
        stop_reason=batch.stop_reason,
        successful=batch.successful,
    )
    return {"run_id": run_id, "successful": batch.successful, **counts}


def ingest_json(
    store: PostRepository,
    path: str | Path,
    *,
    handle: str = "",
    mode: str = "incremental",
    relation: str = "own_post",
) -> dict[str, Any]:
    return ingest_batch(
        store,
        load_extracted_batch(path, handle),
        mode=mode,
        relation=relation,
    )
