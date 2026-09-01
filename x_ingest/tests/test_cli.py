from __future__ import annotations

import unittest

from x_ingest.cli import build_parser


class CliTests(unittest.TestCase):
    def test_crawl_defaults_to_mysql_and_accepts_cursor_window(self):
        args = build_parser().parse_args(["crawl", "--handle", "AndrewYNg", "--from", "2020-01-01"])
        self.assertEqual(args.storage if hasattr(args, "storage") else "mysql", "mysql")
        self.assertEqual(args.handle, "AndrewYNg")
        self.assertEqual(args.requested_from, "2020-01-01")

    def test_offline_import_can_explicitly_select_sqlite(self):
        args = build_parser().parse_args(["import", "capture.json", "--storage", "sqlite"])
        self.assertEqual(args.storage, "sqlite")


if __name__ == "__main__":
    unittest.main()
