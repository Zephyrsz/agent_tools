from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from x_ingest.obsidian import export_posts
from x_ingest.store import SQLitePostStore
from x_ingest.tests.test_store import sample_post


class ObsidianExportTests(unittest.TestCase):
    def test_export_is_stable_and_keeps_video_posts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vault = root / "vault"
            (vault / ".obsidian").mkdir(parents=True)
            with SQLitePostStore(root / "posts.sqlite3") as store:
                video = PostWithVideo.create()
                store.upsert_posts([sample_post(), video], handle="Example")
                first = export_posts(store, vault=vault, handle="Example")
                second = export_posts(store, vault=vault, handle="Example")

            self.assertEqual(len(first), 2)
            self.assertEqual(second, [])
            content = first[0].read_text(encoding="utf-8")
            self.assertIn('post_id: "123"', content)
            self.assertIn('published: "2026-08-29T10:00:00.000Z"', content)


class PostWithVideo:
    @staticmethod
    def create():
        value = sample_post("124", "video post").to_mapping()
        value["hasVideo"] = True
        from x_ingest.models import Post

        return Post.from_mapping(value)


if __name__ == "__main__":
    unittest.main()
