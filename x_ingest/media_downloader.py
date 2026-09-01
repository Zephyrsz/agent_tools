"""Atomic local image downloader backed by repository media state."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen


class MediaDownloader:
    def __init__(
        self,
        repository: Any,
        root: str | Path,
        *,
        opener: Callable[[str], tuple[bytes, str]] | None = None,
        max_retries: int = 3,
        retry_delay: float = 0.2,
    ) -> None:
        self.repository = repository
        self.root = Path(root).expanduser().resolve()
        self.opener = opener or self._open
        self.max_retries = max(1, int(max_retries))
        self.retry_delay = max(0.0, float(retry_delay))

    @staticmethod
    def _open(url: str) -> tuple[bytes, str]:
        request = Request(url, headers={"User-Agent": "x_ingest/1.0"})
        with urlopen(request, timeout=30) as response:  # noqa: S310 - URL comes from X media
            return response.read(), response.headers.get_content_type()

    def retry_pending(self, *, limit: int = 1000) -> dict[str, int]:
        rows = self.repository.list_pending_media(limit=max(1, int(limit)))
        counts = {"ready": 0, "failed": 0}
        for row in rows:
            try:
                self._download_one(row)
                counts["ready"] += 1
            except Exception as exc:
                counts["failed"] += 1
                self.repository.mark_media_failed(
                    int(row["media_id"]), error=str(exc)[:500]
                )
        return counts

    def _download_one(self, row: dict[str, Any]) -> None:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                body, mime = self.opener(str(row["remote_url"]))
                if not body:
                    raise ValueError("empty media response")
                self._persist(row, body, mime)
                return
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.max_retries and self.retry_delay:
                    time.sleep(self.retry_delay * (attempt + 1))
        assert last_error is not None
        raise last_error

    def _persist(self, row: dict[str, Any], body: bytes, mime: str) -> None:
        handle = str(row.get("author_handle") or "unknown").strip().lstrip("@").lower()
        created_at = str(row.get("created_at") or "1970-01-01T00:00:00Z")
        year, month = created_at[:4], created_at[5:7]
        extension = mimetypes.guess_extension(mime or "") or Path(str(row.get("remote_url", ""))).suffix or ".bin"
        if extension.lower() == ".jpe":
            extension = ".jpg"
        relative = Path(handle) / "images" / year / month / f"{row['post_id']}-{int(row['ordinal'])}{extension.lower()}"
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        digest = hashlib.sha256(body).hexdigest()
        self.repository.mark_media_ready(
            int(row["media_id"]),
            local_path=relative.as_posix(),
            sha256=digest,
            size_bytes=len(body),
            mime_type=mime or "application/octet-stream",
        )
