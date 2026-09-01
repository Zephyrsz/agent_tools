from __future__ import annotations

import sqlite3
import unittest
import re

from x_ingest.models import Post
from x_ingest.mysql_store import MySQLPostRepository


class SQLiteDBAPIFake:
    """A DB-API fake that accepts MySQL-style ``%s`` parameters."""

    def __init__(self) -> None:
        self.raw = sqlite3.connect(":memory:")
        self.raw.row_factory = sqlite3.Row

    def cursor(self):
        return self

    def execute(self, sql, params=()):
        sql = sql.replace("%s", "?")
        sql = sql.replace(" BIGINT UNSIGNED", " INTEGER")
        sql = sql.replace(" BIGINT", " INTEGER")
        sql = sql.replace(" AUTO_INCREMENT", "")
        sql = sql.replace(" ON UPDATE CURRENT_TIMESTAMP", "")
        sql = re.sub(r"\s+ENGINE=InnoDB\s+DEFAULT CHARSET=utf8mb4", "", sql)
        sql = re.sub(r"UNIQUE KEY \w+ \(([^)]+)\)", r"UNIQUE (\1)", sql)
        sql = re.sub(r",?\s*KEY \w+ \([^)]+\)", "", sql)
        self.cursor_obj = self.raw.execute(sql, tuple(params or ()))
        return self

    def executemany(self, sql, seq):
        sql = sql.replace("%s", "?")
        self.cursor_obj = self.raw.executemany(sql, seq)
        return self

    def fetchone(self):
        return self.cursor_obj.fetchone()

    def fetchall(self):
        return self.cursor_obj.fetchall()

    @property
    def lastrowid(self):
        return self.cursor_obj.lastrowid

    @property
    def description(self):
        return self.cursor_obj.description

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def post(post_id: str = "100", text: str = "hello") -> Post:
    return Post.from_mapping(
        {
            "postId": post_id,
            "url": f"https://x.com/example/status/{post_id}",
            "timestamp": "2026-08-29T10:00:00Z",
            "text": text,
            "author": {"handle": "@example", "displayName": "Example"},
            "images": [{"url": "https://pbs.twimg.com/media/a.jpg", "alt": "A"}],
        }
    )


class MySQLPostRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = SQLiteDBAPIFake()
        self.store = MySQLPostRepository(connection=self.connection)
        self.store.initialize()

    def tearDown(self) -> None:
        self.store.close()

    def test_upsert_is_idempotent_and_tracks_media_state(self) -> None:
        first = self.store.upsert_posts([post()], handle="Example")
        second = self.store.upsert_posts([post()], handle="Example")

        self.assertEqual(first["inserted"], 1)
        self.assertEqual(second["unchanged"], 1)
        self.assertEqual(self.store.query_posts(handle="example")[0]["text"], "hello")
        media = self.store.get_media("100")
        self.assertEqual(media[0]["state"], "pending")
        self.store.update_media_state("100", 1, state="ready", local_path="images/a.jpg")
        self.assertEqual(self.store.get_media("100")[0]["state"], "ready")

    def test_failed_media_is_queued_for_retry_until_retry_limit(self) -> None:
        self.store.upsert_posts([post()], handle="example")
        self.store.update_media_state("100", 1, state="failed", error="HTTP 503")

        retry = self.store.list_retryable_media(max_retries=2)
        self.assertEqual(retry[0]["post_id"], "100")
        self.assertEqual(retry[0]["retry_count"], 1)
        self.store.update_media_state("100", 1, state="failed", error="HTTP 503")
        self.assertEqual(self.store.list_retryable_media(max_retries=2), [])

    def test_crawl_success_advances_state_but_failure_does_not(self) -> None:
        run = self.store.begin_crawl("example", mode="backfill", started_at="2026-08-30T00:00:00Z")
        self.store.upsert_posts([post()], handle="example")
        self.store.finish_crawl(run, fetched_count=1, inserted_count=1, updated_count=0, successful=False)
        self.assertIsNone(self.store.get_state("example"))

        run = self.store.begin_crawl("example", started_at="2026-08-31T00:00:00Z")
        self.store.finish_crawl(run, fetched_count=1, inserted_count=0, updated_count=0)
        state = self.store.get_state("example")
        self.assertEqual(state["newest_seen_id"], "100")

    def test_candidate_queue_round_trip_and_retry_query(self) -> None:
        self.store.enqueue_candidate("example", "100", "https://x.com/example/status/100")
        self.store.enqueue_candidate("example", "101", "https://x.com/example/status/101")
        candidates = self.store.list_candidates("example", statuses=("pending",), limit=10)
        self.assertEqual([item["post_id"] for item in candidates], ["100", "101"])
        self.store.mark_candidate("example", "100", status="error", error="timeout")
        retryable = self.store.list_candidates("example", statuses=("error",), limit=10)
        self.assertEqual(retryable[0]["attempts"], 1)
        self.assertIsNone(retryable[0]["resolved_at"])


if __name__ == "__main__":
    unittest.main()
