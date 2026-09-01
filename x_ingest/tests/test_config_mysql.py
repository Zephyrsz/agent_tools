from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from x_ingest.config import AppConfig, load_config


class MySQLConfigTests(unittest.TestCase):
    def test_rejects_empty_mysql_database(self) -> None:
        with self.assertRaises(ValueError):
            from x_ingest.config import MySQLConfig

            MySQLConfig(database="")

    def test_loads_mysql_and_mcp_settings_without_persisting_password(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "mysql": {
                            "host": "db.internal",
                            "port": 3307,
                            "user": "archiver",
                            "password_env": "X_INGEST_DB_PASSWORD",
                            "database": "x_archive",
                        },
                        "browser": {
                            "mcp_command": ["node", "server.js"],
                            "cdp_url": "http://127.0.0.1:9222",
                        },
                        "media_root": "media",
                        "users": [{"handle": "@AndrewYNg"}],
                    }
                ),
                encoding="utf-8",
            )
            os.environ["X_INGEST_DB_PASSWORD"] = "secret"
            try:
                config = load_config(path)
            finally:
                os.environ.pop("X_INGEST_DB_PASSWORD", None)

            self.assertEqual(config.mysql.host, "db.internal")
            self.assertEqual(config.mysql.port, 3307)
            self.assertEqual(config.mysql.password, "secret")
            self.assertEqual(config.media_root, (Path(temp) / "media").resolve())
            self.assertEqual(config.browser.mcp_command, ("node", "server.js"))
            self.assertIn("andrewyng", config.users)

    def test_defaults_to_mysql_and_requires_a_database_name(self) -> None:
        config = AppConfig()
        self.assertEqual(config.mysql.host, "127.0.0.1")
        self.assertEqual(config.mysql.database, "x_ingest")


if __name__ == "__main__":
    unittest.main()
