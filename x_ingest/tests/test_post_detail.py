from __future__ import annotations

import unittest

from x_ingest.models import PostDetail


class PostDetailTests(unittest.TestCase):
    def test_only_original_text_or_image_is_archivable(self) -> None:
        base = {
            "postId": "123",
            "url": "https://x.com/example/status/123",
            "timestamp": "2026-08-29T10:00:00Z",
            "text": "hello",
            "author": {"handle": "@example", "displayName": "Example"},
        }
        self.assertEqual(PostDetail.from_mapping(base).decision_for("example"), "saved")
        self.assertEqual(PostDetail.from_mapping({**base, "isReply": True}).decision_for("example"), "reply")
        self.assertEqual(PostDetail.from_mapping({**base, "isQuote": True}).decision_for("example"), "quote")
        self.assertEqual(PostDetail.from_mapping({**base, "isRepost": True}).decision_for("example"), "repost")
        self.assertEqual(PostDetail.from_mapping({**base, "hasVideo": True}).decision_for("example"), "video")


if __name__ == "__main__":
    unittest.main()
