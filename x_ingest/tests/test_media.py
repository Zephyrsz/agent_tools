from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from x_ingest.media_downloader import MediaDownloader


class FakeRepository:
    def __init__(self):
        self.pending = [{
            "media_id": 4,
            "post_id": "123",
            "ordinal": 1,
            "remote_url": "https://pbs.twimg.com/media/a.jpg",
            "created_at": "2026-08-29T10:00:00.000Z",
            "author_handle": "example",
        }]
        self.ready = []
        self.failed = []

    def list_pending_media(self, **kwargs):
        return list(self.pending)

    def mark_media_ready(self, media_id, **kwargs):
        self.ready.append((media_id, kwargs))

    def mark_media_failed(self, media_id, **kwargs):
        self.failed.append((media_id, kwargs))


class MediaDownloaderTests(unittest.TestCase):
    def test_downloads_image_atomically_and_marks_ready(self):
        repo = FakeRepository()

        def opener(_url):
            return b"image-bytes", "image/jpeg"

        with tempfile.TemporaryDirectory() as temp:
            result = MediaDownloader(repo, Path(temp), opener=opener).retry_pending()
            path = Path(temp) / "example" / "images" / "2026" / "08" / "123-1.jpg"
            self.assertEqual(result["ready"], 1)
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes(), b"image-bytes")
            self.assertEqual(repo.ready[0][0], 4)
            self.assertEqual(repo.ready[0][1]["local_path"], "example/images/2026/08/123-1.jpg")

    def test_failed_download_is_retryable(self):
        repo = FakeRepository()

        def opener(_url):
            raise OSError("network down")

        with tempfile.TemporaryDirectory() as temp:
            result = MediaDownloader(repo, Path(temp), opener=opener, max_retries=2).retry_pending()
            self.assertEqual(result["failed"], 1)
            self.assertEqual(repo.failed[0][0], 4)


if __name__ == "__main__":
    unittest.main()
