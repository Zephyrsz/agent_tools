from __future__ import annotations

import asyncio
import unittest

from x_ingest.crawler import CrawlCoordinator


class FakeRepository:
    def __init__(self) -> None:
        self.posts = []
        self.candidates = []
        self.updated = []
        self.finished = []
        self.run_id = 7

    def begin_crawl(self, handle, **kwargs):
        return self.run_id

    def add_candidate(self, run_id, handle, url, **metadata):
        candidate_id = len(self.candidates) + 1
        self.candidates.append({"id": candidate_id, "url": url, **metadata})
        return candidate_id

    def update_candidate(self, candidate_id, status, **metadata):
        self.updated.append((candidate_id, status, metadata))

    def upsert_posts(self, posts, *, handle, **kwargs):
        values = list(posts)
        self.posts.extend(values)
        return {"fetched": len(values), "inserted": len(values), "updated": 0, "unchanged": 0, "skipped": 0}

    def finish_crawl(self, run_id, **kwargs):
        self.finished.append((run_id, kwargs))


class FakeGateway:
    def __init__(self):
        self.details = {
            "https://x.com/example/status/1": {
                "postId": "1", "url": "https://x.com/example/status/1",
                "timestamp": "2026-08-01T00:00:00Z", "text": "original",
                "author": {"handle": "@example", "displayName": "Example"},
            },
            "https://x.com/example/status/2": {
                "postId": "2", "url": "https://x.com/example/status/2",
                "timestamp": "2026-08-02T00:00:00Z", "text": "reply",
                "author": {"handle": "@example"}, "isReply": True,
            },
        }

    async def start(self):
        return None

    async def close(self):
        return None

    async def is_authenticated(self):
        return True

    async def discover_candidates(self, handle, **kwargs):
        return {"status": "complete", "candidates": [{"url": url} for url in self.details]}

    async def extract_detail(self, url):
        return self.details[url]


class CrawlCoordinatorTests(unittest.TestCase):
    def test_saves_only_original_details_and_marks_skips(self):
        async def scenario():
            repository = FakeRepository()
            coordinator = CrawlCoordinator(repository, FakeGateway())
            result = await coordinator.crawl("@Example")
            self.assertEqual(result["saved"], 1)
            self.assertEqual(len(repository.posts), 1)
            self.assertEqual(repository.updated[0][1], "saved")
            self.assertEqual(repository.updated[1][1], "reply")
            self.assertTrue(repository.finished[0][1]["successful"])

        asyncio.run(scenario())

    def test_partial_discovery_does_not_advance_state(self):
        class PartialGateway(FakeGateway):
            async def discover_candidates(self, handle, **kwargs):
                return {"status": "partial", "stopReason": "boundary" , "candidates": []}

        async def scenario():
            repository = FakeRepository()
            coordinator = CrawlCoordinator(repository, PartialGateway())
            result = await coordinator.crawl("example")
            self.assertFalse(result["successful"])
            self.assertFalse(repository.finished[0][1]["successful"])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
