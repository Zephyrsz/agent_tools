"""Readers for extractor output formats."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Post, normalize_handle


@dataclass(frozen=True)
class ExtractedBatch:
    posts: tuple[Post, ...]
    handle: str
    captured_at: str | None = None
    source_page: str | None = None
    status: str = "complete"
    stop_reason: str = ""

    @property
    def successful(self) -> bool:
        return self.status.lower() != "partial" and not self.stop_reason


def load_extracted_batch(path: str | Path, handle: str = "") -> ExtractedBatch:
    source = Path(path).expanduser().resolve()
    data = json.loads(source.read_text(encoding="utf-8"))
    if isinstance(data, list):
        metadata: dict[str, Any] = {}
        raw_posts = data
    elif isinstance(data, dict) and isinstance(data.get("posts"), list):
        metadata = data
        raw_posts = data["posts"]
    else:
        raise ValueError(
            "input JSON must be a list or an object containing a posts list"
        )

    batch_handle = normalize_handle(handle or str(metadata.get("handle", "")))
    if not batch_handle and raw_posts:
        author = (
            raw_posts[0].get("author", {}) if isinstance(raw_posts[0], dict) else {}
        )
        batch_handle = normalize_handle(str(author.get("handle", "")))
    if not batch_handle:
        raise ValueError("timeline handle is required")

    posts: list[Post] = []
    for value in raw_posts:
        if isinstance(value, dict):
            posts.append(Post.from_mapping(value, batch_handle))
    return ExtractedBatch(
        posts=tuple(posts),
        handle=batch_handle,
        captured_at=str(metadata.get("capturedAt", "")).strip() or None,
        source_page=str(metadata.get("sourcePage", "")).strip() or None,
        status=str(metadata.get("status", "complete")).strip() or "complete",
        stop_reason=str(metadata.get("stopReason", "")).strip(),
    )
