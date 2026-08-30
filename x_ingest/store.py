"""SQLite storage for incrementally archiving X/Twitter posts.

The database is deliberately independent from the browser crawler and the
Obsidian writer.  A crawler can import each extracted batch as soon as it is
available; the post ID is the idempotency key and ``created_at`` + ``post_id``
is the stable chronological cursor.

"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .models import Post, normalize_handle, normalize_timestamp, utc_now


SCHEMA_VERSION = 1


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    account_id INTEGER PRIMARY KEY,
    handle TEXT NOT NULL COLLATE NOCASE UNIQUE,
    display_name TEXT NOT NULL DEFAULT '',
    profile_url TEXT,
    first_seen_at TEXT,
    last_seen_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    post_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_epoch INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    author_handle TEXT NOT NULL,
    author_display_name TEXT NOT NULL DEFAULT '',
    post_kind TEXT NOT NULL DEFAULT 'post',
    has_video INTEGER NOT NULL DEFAULT 0 CHECK (has_video IN (0, 1)),
    is_pinned INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0, 1)),
    content_hash TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    obsidian_path TEXT,
    updated_at TEXT NOT NULL
);

-- A post can occur in more than one collected timeline, so the collection
-- account is kept in a link table instead of duplicating the post row.
CREATE TABLE IF NOT EXISTS account_posts (
    account_id INTEGER NOT NULL,
    post_id TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT 'own_post',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    PRIMARY KEY (account_id, post_id),
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE,
    FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS media (
    media_id INTEGER PRIMARY KEY,
    post_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    media_type TEXT NOT NULL DEFAULT 'image',
    remote_url TEXT NOT NULL,
    alt_text TEXT NOT NULL DEFAULT '',
    local_path TEXT,
    width INTEGER,
    height INTEGER,
    UNIQUE (post_id, ordinal, remote_url),
    FOREIGN KEY (post_id) REFERENCES posts(post_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS crawl_runs (
    run_id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    mode TEXT NOT NULL DEFAULT 'incremental',
    requested_from TEXT,
    requested_until TEXT,
    fetched_count INTEGER NOT NULL DEFAULT 0,
    inserted_count INTEGER NOT NULL DEFAULT 0,
    updated_count INTEGER NOT NULL DEFAULT 0,
    unchanged_count INTEGER NOT NULL DEFAULT 0,
    skipped_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    stop_reason TEXT,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS crawl_state (
    account_id INTEGER PRIMARY KEY,
    newest_seen_at TEXT,
    newest_seen_id TEXT,
    oldest_seen_at TEXT,
    oldest_seen_id TEXT,
    last_successful_run_id INTEGER,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (account_id) REFERENCES accounts(account_id) ON DELETE CASCADE,
    FOREIGN KEY (last_successful_run_id) REFERENCES crawl_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_posts_created
    ON posts (created_epoch DESC, post_id DESC);
CREATE INDEX IF NOT EXISTS idx_posts_author_created
    ON posts (author_handle COLLATE NOCASE, created_epoch DESC, post_id DESC);
CREATE INDEX IF NOT EXISTS idx_account_posts_post
    ON account_posts (post_id);
CREATE INDEX IF NOT EXISTS idx_account_posts_account
    ON account_posts (account_id, post_id);
CREATE INDEX IF NOT EXISTS idx_media_post
    ON media (post_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_runs_account_started
    ON crawl_runs (account_id, started_at DESC);
"""


class SQLitePostStore:
    """Small transactional repository used by the crawler and exporters."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        self.connection.execute("PRAGMA busy_timeout = 5000")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SQLitePostStore":
        self.initialize()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()

    def initialize(self) -> None:
        self.connection.executescript(SCHEMA)
        self.connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        self.connection.commit()

    def _ensure_account(
        self,
        handle: str,
        display_name: str = "",
        profile_url: str = "",
        seen_at: str | None = None,
    ) -> int:
        handle = normalize_handle(handle)
        if not handle:
            raise ValueError("account handle is required")
        seen_at = seen_at or utc_now()
        self.connection.execute(
            """
            INSERT INTO accounts(
                handle, display_name, profile_url, first_seen_at, last_seen_at,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(handle) DO UPDATE SET
                display_name = CASE WHEN excluded.display_name <> ''
                    THEN excluded.display_name ELSE accounts.display_name END,
                profile_url = CASE WHEN excluded.profile_url <> ''
                    THEN excluded.profile_url ELSE accounts.profile_url END,
                last_seen_at = excluded.last_seen_at,
                updated_at = excluded.updated_at
            """,
            (
                handle,
                display_name,
                profile_url or None,
                seen_at,
                seen_at,
                seen_at,
                seen_at,
            ),
        )
        row = self.connection.execute(
            "SELECT account_id FROM accounts WHERE handle = ? COLLATE NOCASE", (handle,)
        ).fetchone()
        assert row is not None
        return int(row[0])

    def begin_crawl(
        self,
        handle: str,
        *,
        mode: str = "incremental",
        requested_from: str | None = None,
        requested_until: str | None = None,
        started_at: str | None = None,
    ) -> int:
        started_at = started_at or utc_now()
        account_id = self._ensure_account(handle, seen_at=started_at)
        cursor = self.connection.execute(
            """
            INSERT INTO crawl_runs(account_id, started_at, mode, requested_from, requested_until)
            VALUES (?, ?, ?, ?, ?)
            """,
            (account_id, started_at, mode, requested_from, requested_until),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def finish_crawl(
        self,
        run_id: int,
        *,
        fetched_count: int,
        inserted_count: int,
        updated_count: int,
        unchanged_count: int = 0,
        skipped_count: int = 0,
        error_count: int = 0,
        stop_reason: str = "",
        successful: bool = True,
        finished_at: str | None = None,
    ) -> None:
        finished_at = finished_at or utc_now()
        row = self.connection.execute(
            "SELECT account_id FROM crawl_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"unknown crawl run: {run_id}")
        account_id = int(row[0])
        self.connection.execute(
            """
            UPDATE crawl_runs SET finished_at = ?, fetched_count = ?, inserted_count = ?,
                updated_count = ?, unchanged_count = ?, skipped_count = ?,
                error_count = ?, stop_reason = ?
            WHERE run_id = ?
            """,
            (
                finished_at,
                fetched_count,
                inserted_count,
                updated_count,
                unchanged_count,
                skipped_count,
                error_count,
                stop_reason or None,
                run_id,
            ),
        )
        if successful:
            self._refresh_state(account_id, run_id, finished_at)
        self.connection.commit()

    def _refresh_state(self, account_id: int, run_id: int, updated_at: str) -> None:
        newest = self.connection.execute(
            """
            SELECT p.created_at, p.post_id FROM posts p
            JOIN account_posts ap ON ap.post_id = p.post_id
            WHERE ap.account_id = ?
            ORDER BY p.created_epoch DESC, p.post_id DESC LIMIT 1
            """,
            (account_id,),
        ).fetchone()
        oldest = self.connection.execute(
            """
            SELECT p.created_at, p.post_id FROM posts p
            JOIN account_posts ap ON ap.post_id = p.post_id
            WHERE ap.account_id = ?
            ORDER BY p.created_epoch ASC, p.post_id ASC LIMIT 1
            """,
            (account_id,),
        ).fetchone()
        self.connection.execute(
            """
            INSERT INTO crawl_state(
                account_id, newest_seen_at, newest_seen_id, oldest_seen_at, oldest_seen_id,
                last_successful_run_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                newest_seen_at = excluded.newest_seen_at,
                newest_seen_id = excluded.newest_seen_id,
                oldest_seen_at = excluded.oldest_seen_at,
                oldest_seen_id = excluded.oldest_seen_id,
                last_successful_run_id = excluded.last_successful_run_id,
                updated_at = excluded.updated_at
            """,
            (
                account_id,
                newest[0] if newest else None,
                newest[1] if newest else None,
                oldest[0] if oldest else None,
                oldest[1] if oldest else None,
                run_id,
                updated_at,
            ),
        )

    def upsert_posts(
        self,
        posts: Iterable[Post | dict[str, Any]],
        *,
        handle: str,
        captured_at: str | None = None,
        relation: str = "own_post",
    ) -> dict[str, int]:
        """Import one extracted batch in one transaction.

        Existing post IDs are updated in place, so repeated crawler runs are
        idempotent.  Invalid records are counted as skipped and do not abort
        the valid records in the same batch.
        """

        captured_at = captured_at or utc_now()
        target_handle = normalize_handle(handle)
        counts = {
            "fetched": 0,
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "skipped": 0,
        }
        try:
            self.connection.execute("BEGIN")
            account_id = self._ensure_account(target_handle, seen_at=captured_at)
            account_name_refreshed = False
            for value in posts:
                counts["fetched"] += 1
                try:
                    post = (
                        value
                        if isinstance(value, Post)
                        else Post.from_mapping(value, target_handle)
                    )
                    if (
                        not account_name_refreshed
                        and post.author_handle == target_handle
                        and post.author_display_name
                    ):
                        self._ensure_account(
                            target_handle,
                            display_name=post.author_display_name,
                            profile_url=f"https://x.com/{target_handle}",
                            seen_at=captured_at,
                        )
                        account_name_refreshed = True
                    old = self.connection.execute(
                        "SELECT content_hash FROM posts WHERE post_id = ?",
                        (post.post_id,),
                    ).fetchone()
                    self.connection.execute(
                        """
                        INSERT INTO posts(
                            post_id, url, created_at, created_epoch, text, author_handle,
                            author_display_name, post_kind, has_video, is_pinned,
                            content_hash, raw_json, first_seen_at, last_seen_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(post_id) DO UPDATE SET
                            url = excluded.url,
                            created_at = excluded.created_at,
                            created_epoch = excluded.created_epoch,
                            text = excluded.text,
                            author_handle = excluded.author_handle,
                            author_display_name = excluded.author_display_name,
                            post_kind = excluded.post_kind,
                            has_video = excluded.has_video,
                            is_pinned = excluded.is_pinned,
                            content_hash = excluded.content_hash,
                            raw_json = excluded.raw_json,
                            last_seen_at = excluded.last_seen_at,
                            updated_at = excluded.updated_at
                        """,
                        (
                            post.post_id,
                            post.url,
                            post.created_at,
                            post.created_epoch,
                            post.text,
                            post.author_handle,
                            post.author_display_name,
                            post.post_kind,
                            int(post.has_video),
                            int(post.is_pinned),
                            post.content_hash,
                            post.raw_json,
                            captured_at,
                            captured_at,
                            captured_at,
                        ),
                    )
                    self.connection.execute(
                        """
                        INSERT INTO account_posts(account_id, post_id, relation, first_seen_at, last_seen_at)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(account_id, post_id) DO UPDATE SET
                            relation = excluded.relation,
                            last_seen_at = excluded.last_seen_at
                        """,
                        (account_id, post.post_id, relation, captured_at, captured_at),
                    )
                    self.connection.execute(
                        "DELETE FROM media WHERE post_id = ?", (post.post_id,)
                    )
                    for item in post.media:
                        self.connection.execute(
                            """
                            INSERT INTO media(
                                post_id, ordinal, media_type, remote_url, alt_text,
                                local_path, width, height
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                post.post_id,
                                item.ordinal,
                                item.media_type,
                                item.remote_url,
                                item.alt_text,
                                item.local_path,
                                item.width,
                                item.height,
                            ),
                        )
                    if old is None:
                        counts["inserted"] += 1
                    elif old[0] == post.content_hash:
                        counts["unchanged"] += 1
                    else:
                        counts["updated"] += 1
                except (TypeError, ValueError, sqlite3.Error):
                    counts["skipped"] += 1
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return counts

    def get_state(self, handle: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            """
            SELECT a.handle, cs.newest_seen_at, cs.newest_seen_id,
                   cs.oldest_seen_at, cs.oldest_seen_id,
                   cs.last_successful_run_id, cs.updated_at
            FROM accounts a JOIN crawl_state cs ON cs.account_id = a.account_id
            WHERE a.handle = ? COLLATE NOCASE
            """,
            (normalize_handle(handle),),
        ).fetchone()
        return dict(row) if row else None

    def query_posts(
        self,
        *,
        handle: str | None = None,
        after: str | None = None,
        after_id: str | None = None,
        before: str | None = None,
        before_id: str | None = None,
        contains: str | None = None,
        order: str = "asc",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        joins = ""
        if handle:
            joins = "JOIN account_posts ap ON ap.post_id = p.post_id JOIN accounts a ON a.account_id = ap.account_id"
            clauses.append("a.handle = ? COLLATE NOCASE")
            params.append(normalize_handle(handle))
        if after:
            _, after_epoch = normalize_timestamp(after)
            clauses.append(
                "(p.created_epoch > ? OR (p.created_epoch = ? AND p.post_id > ?))"
            )
            params.extend((after_epoch, after_epoch, after_id or ""))
        if before:
            _, before_epoch = normalize_timestamp(before)
            clauses.append(
                "(p.created_epoch < ? OR (p.created_epoch = ? AND p.post_id < ?))"
            )
            params.extend((before_epoch, before_epoch, before_id or "~"))
        if contains:
            clauses.append("p.text LIKE ? COLLATE NOCASE")
            params.append(f"%{contains}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        direction = "DESC" if order.lower() == "desc" else "ASC"
        sql = f"""
            SELECT p.post_id, p.url, p.created_at, p.text, p.author_handle,
                   p.author_display_name, p.post_kind, p.has_video, p.is_pinned,
                   p.first_seen_at, p.last_seen_at, p.obsidian_path
            FROM posts p {joins}
            {where}
            ORDER BY p.created_epoch {direction}, p.post_id {direction}
            LIMIT ?
        """
        params.append(max(1, min(int(limit), 10000)))
        rows = self.connection.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_media(self, post_id: str) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            """
            SELECT ordinal, media_type, remote_url, alt_text, local_path, width, height
            FROM media WHERE post_id = ? ORDER BY ordinal ASC
            """,
            (post_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def set_obsidian_path(self, post_id: str, path: str | Path | None) -> None:
        self.connection.execute(
            "UPDATE posts SET obsidian_path = ?, updated_at = ? WHERE post_id = ?",
            (str(path) if path is not None else None, utc_now(), post_id),
        )
        self.connection.commit()
