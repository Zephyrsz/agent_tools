from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from x_ingest.importers import ExtractedBatch
from x_ingest.models import Post
from x_ingest.service import ingest_batch
from x_ingest.store import SQLitePostStore


def sample_post(post_id: str = "123", text: str = "hello") -> Post:
    return Post.from_mapping(
        {
            "url": f"https://x.com/Example/status/{post_id}",
            "timestamp": "2026-08-29T10:00:00.000Z",
            "text": text,
            "author": {"displayName": "Example User", "handle": "@Example"},
            "images": [
                {"url": "https://pbs.twimg.com/media/example.jpg", "alt": "Example"}
            ],
            "hasVideo": False,
        }
    )


class SQLitePostStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "posts.sqlite3"
        self.store = SQLitePostStore(self.database)
        self.store.initialize()

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_repeated_import_is_idempotent(self) -> None:
        first = self.store.upsert_posts([sample_post()], handle="Example")
        second = self.store.upsert_posts([sample_post()], handle="Example")

        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["unchanged"], 1)
        self.assertEqual(len(self.store.query_posts(handle="Example")), 1)
        self.assertEqual(len(self.store.get_media("123")), 1)

    def test_changed_content_updates_existing_post(self) -> None:
        self.store.upsert_posts([sample_post(text="before")], handle="Example")
        result = self.store.upsert_posts([sample_post(text="after")], handle="Example")

        self.assertEqual(result["updated"], 1)
        self.assertEqual(self.store.query_posts(handle="Example")[0]["text"], "after")

    def test_article_without_tweet_text_is_stored(self) -> None:
        article = Post.from_mapping(
            {
                "url": "https://x.com/Example/status/456",
                "timestamp": "2026-08-30T10:00:00.000Z",
                "text": "",
                "author": {"displayName": "Example User", "handle": "@Example"},
                "postKind": "article",
                "articleUrl": "https://x.com/i/article/456",
            }
        )

        result = self.store.upsert_posts([article], handle="Example")
        stored = self.store.query_posts(handle="Example")[0]

        self.assertEqual(result["inserted"], 1)
        self.assertEqual(stored["post_kind"], "article")
        self.assertEqual(stored["text"], "")

    def test_partial_batch_does_not_advance_success_cursor(self) -> None:
        batch = ExtractedBatch(
            posts=(sample_post(),),
            handle="example",
            status="partial",
            stop_reason="timeline load failed",
        )
        result = ingest_batch(self.store, batch, mode="backfill")

        self.assertFalse(result["successful"])
        self.assertIsNone(self.store.get_state("example"))
        self.assertEqual(len(self.store.query_posts(handle="example")), 1)

    def test_successful_batch_saves_both_cursor_parts(self) -> None:
        batch = ExtractedBatch(posts=(sample_post(),), handle="example")
        ingest_batch(self.store, batch)

        state = self.store.get_state("example")
        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state["newest_seen_at"], "2026-08-29T10:00:00.000Z")
        self.assertEqual(state["newest_seen_id"], "123")


if __name__ == "__main__":
    unittest.main()
