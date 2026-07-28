from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from icloud_tools.icloud_drive import (
    ICloudDriveError,
    download,
    list_items,
    read_file,
    resolve_inside,
    upload,
)


class ICloudDriveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name).resolve()
        self.cloud = self.base / "cloud"
        self.cloud.mkdir()
        self.local = self.base / "local"
        self.local.mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_resolve_inside_rejects_parent_escape(self) -> None:
        with self.assertRaises(ICloudDriveError):
            resolve_inside(self.cloud, "../outside.txt")

    def test_resolve_inside_rejects_absolute_path(self) -> None:
        with self.assertRaises(ICloudDriveError):
            resolve_inside(self.cloud, self.local / "outside.txt")

    def test_resolve_inside_rejects_symlink_escape(self) -> None:
        (self.cloud / "escape").symlink_to(self.local, target_is_directory=True)
        with self.assertRaises(ICloudDriveError):
            resolve_inside(self.cloud, "escape/file.txt")

    def test_upload_and_read_text_file(self) -> None:
        source = self.local / "hello.txt"
        source.write_text("hello iCloud", encoding="utf-8")

        destination = upload(
            self.cloud, source, "Documents/hello.txt", overwrite=False
        )

        self.assertEqual(destination, self.cloud / "Documents" / "hello.txt")
        self.assertEqual(
            read_file(
                self.cloud,
                "Documents/hello.txt",
                encoding="utf-8",
                max_bytes=1024,
            ),
            "hello iCloud",
        )

    def test_upload_refuses_existing_file_without_overwrite(self) -> None:
        source = self.local / "hello.txt"
        source.write_text("new", encoding="utf-8")
        target = self.cloud / "hello.txt"
        target.write_text("old", encoding="utf-8")

        with self.assertRaises(ICloudDriveError):
            upload(self.cloud, source, None, overwrite=False)

        self.assertEqual(target.read_text(encoding="utf-8"), "old")

    def test_upload_overwrites_existing_file(self) -> None:
        source = self.local / "hello.txt"
        source.write_text("new", encoding="utf-8")
        target = self.cloud / "hello.txt"
        target.write_text("old", encoding="utf-8")

        upload(self.cloud, source, None, overwrite=True)

        self.assertEqual(target.read_text(encoding="utf-8"), "new")

    def test_upload_directory_and_list_recursively(self) -> None:
        source = self.local / "project"
        source.mkdir()
        (source / "one.txt").write_text("one", encoding="utf-8")
        nested = source / "nested"
        nested.mkdir()
        (nested / "two.txt").write_text("two", encoding="utf-8")

        upload(self.cloud, source, "Backups/project", overwrite=False)
        entries = list_items(self.cloud, "Backups", recursive=True)

        self.assertEqual(
            [entry["path"] for entry in entries],
            ["project", "project/nested", "project/nested/two.txt", "project/one.txt"],
        )

    def test_download_file(self) -> None:
        source = self.cloud / "report.txt"
        source.write_text("report", encoding="utf-8")
        destination = self.local / "copies" / "report.txt"

        result = download(
            self.cloud, "report.txt", destination, overwrite=False
        )

        self.assertEqual(result, destination)
        self.assertEqual(destination.read_text(encoding="utf-8"), "report")

    def test_read_limit(self) -> None:
        (self.cloud / "large.txt").write_text("12345", encoding="utf-8")
        with self.assertRaises(ICloudDriveError):
            read_file(self.cloud, "large.txt", encoding="utf-8", max_bytes=4)

    def test_cli_upload_list_read_and_download(self) -> None:
        script = Path(__file__).parents[1] / "icloud_drive.py"
        source = self.local / "source.txt"
        source.write_text("CLI round trip", encoding="utf-8")

        def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--root",
                    str(self.cloud),
                    *arguments,
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        run_cli("upload", str(source), "Docs/source.txt")
        listing = run_cli("list", "Docs", "--json")
        content = run_cli("read", "Docs/source.txt")
        local_copy = self.local / "downloaded.txt"
        run_cli("download", "Docs/source.txt", str(local_copy))

        self.assertEqual(json.loads(listing.stdout)[0]["path"], "source.txt")
        self.assertEqual(content.stdout, "CLI round trip\n")
        self.assertEqual(local_copy.read_text(encoding="utf-8"), "CLI round trip")


if __name__ == "__main__":
    unittest.main()
