"""MySQL DB-API repository for canonical X post ingestion data."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .config import MySQLConfig
from .models import Post, normalize_handle, normalize_timestamp, utc_now


SCHEMA_VERSION = 1

# Statements are intentionally separate: DB-API drivers commonly disallow
# multi-statement execute calls, and this keeps initialization auditable.
SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        `key` VARCHAR(64) NOT NULL PRIMARY KEY,
        value VARCHAR(255) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS accounts (
        account_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        handle VARCHAR(64) NOT NULL,
        display_name VARCHAR(255) NOT NULL DEFAULT '',
        profile_url VARCHAR(2048) NULL,
        first_seen_at VARCHAR(32) NULL,
        last_seen_at VARCHAR(32) NULL,
        created_at VARCHAR(32) NOT NULL,
        updated_at VARCHAR(32) NOT NULL,
        UNIQUE KEY uq_accounts_handle (handle)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS posts (
        post_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
        url VARCHAR(2048) NOT NULL,
        created_at VARCHAR(32) NOT NULL,
        created_epoch BIGINT NOT NULL,
        text LONGTEXT NOT NULL,
        author_handle VARCHAR(64) NOT NULL,
        author_display_name VARCHAR(255) NOT NULL DEFAULT '',
        post_kind VARCHAR(32) NOT NULL DEFAULT 'post',
        has_video TINYINT NOT NULL DEFAULT 0,
        is_pinned TINYINT NOT NULL DEFAULT 0,
        content_hash CHAR(64) NOT NULL,
        raw_json LONGTEXT NOT NULL,
        first_seen_at VARCHAR(32) NOT NULL,
        last_seen_at VARCHAR(32) NOT NULL,
        obsidian_path VARCHAR(4096) NULL,
        updated_at VARCHAR(32) NOT NULL,
        KEY idx_posts_created (created_epoch, post_id),
        KEY idx_posts_author_created (author_handle, created_epoch, post_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS account_posts (
        account_id BIGINT UNSIGNED NOT NULL,
        post_id BIGINT UNSIGNED NOT NULL,
        relation VARCHAR(32) NOT NULL DEFAULT 'own_post',
        first_seen_at VARCHAR(32) NOT NULL,
        last_seen_at VARCHAR(32) NOT NULL,
        PRIMARY KEY (account_id, post_id),
        KEY idx_account_posts_post (post_id),
        CONSTRAINT fk_account_posts_account FOREIGN KEY (account_id)
            REFERENCES accounts(account_id) ON DELETE CASCADE,
        CONSTRAINT fk_account_posts_post FOREIGN KEY (post_id)
            REFERENCES posts(post_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS media (
        media_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        post_id BIGINT UNSIGNED NOT NULL,
        ordinal INT NOT NULL,
        media_type VARCHAR(32) NOT NULL DEFAULT 'image',
        remote_url VARCHAR(4096) NOT NULL,
        alt_text TEXT NOT NULL,
        local_path VARCHAR(4096) NULL,
        width INT NULL,
        height INT NULL,
        state VARCHAR(16) NOT NULL DEFAULT 'pending',
        retry_count INT NOT NULL DEFAULT 0,
        last_error TEXT NULL,
        next_retry_at VARCHAR(32) NULL,
        content_type VARCHAR(255) NULL,
        content_sha256 CHAR(64) NULL,
        byte_size BIGINT UNSIGNED NULL,
        created_at VARCHAR(32) NOT NULL,
        updated_at VARCHAR(32) NOT NULL,
        UNIQUE KEY uq_media_post_ordinal (post_id, ordinal),
        KEY idx_media_retry (state, retry_count, next_retry_at),
        CONSTRAINT fk_media_post FOREIGN KEY (post_id)
            REFERENCES posts(post_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS post_candidates (
        account_id BIGINT UNSIGNED NOT NULL,
        post_id BIGINT UNSIGNED NOT NULL,
        url VARCHAR(2048) NOT NULL,
        discovered_at VARCHAR(32) NOT NULL,
        last_seen_at VARCHAR(32) NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'pending',
        attempts INT NOT NULL DEFAULT 0,
        last_error TEXT NULL,
        raw_json LONGTEXT NULL,
        resolved_at VARCHAR(32) NULL,
        updated_at VARCHAR(32) NOT NULL,
        PRIMARY KEY (account_id, post_id),
        KEY idx_candidate_state (account_id, status, updated_at),
        CONSTRAINT fk_candidates_account FOREIGN KEY (account_id)
            REFERENCES accounts(account_id) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS crawl_runs (
        run_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        account_id BIGINT UNSIGNED NOT NULL,
        started_at VARCHAR(32) NOT NULL,
        finished_at VARCHAR(32) NULL,
        mode VARCHAR(32) NOT NULL DEFAULT 'incremental',
        requested_from VARCHAR(32) NULL,
        requested_until VARCHAR(32) NULL,
        fetched_count INT NOT NULL DEFAULT 0,
        inserted_count INT NOT NULL DEFAULT 0,
        updated_count INT NOT NULL DEFAULT 0,
        unchanged_count INT NOT NULL DEFAULT 0,
        skipped_count INT NOT NULL DEFAULT 0,
        error_count INT NOT NULL DEFAULT 0,
        stop_reason TEXT NULL,
        CONSTRAINT fk_runs_account FOREIGN KEY (account_id)
            REFERENCES accounts(account_id) ON DELETE CASCADE,
        KEY idx_runs_account_started (account_id, started_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS crawl_state (
        account_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
        newest_seen_at VARCHAR(32) NULL,
        newest_seen_id BIGINT UNSIGNED NULL,
        oldest_seen_at VARCHAR(32) NULL,
        oldest_seen_id BIGINT UNSIGNED NULL,
        last_successful_run_id BIGINT UNSIGNED NULL,
        updated_at VARCHAR(32) NOT NULL,
        CONSTRAINT fk_state_account FOREIGN KEY (account_id)
            REFERENCES accounts(account_id) ON DELETE CASCADE,
        CONSTRAINT fk_state_run FOREIGN KEY (last_successful_run_id)
            REFERENCES crawl_runs(run_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
)


class MySQLPostRepository:
    """Transactional MySQL implementation of :class:`PostRepository`.

    ``connection`` and ``connect`` exist for dependency injection. Runtime
    callers normally provide ``MySQLConfig`` and let the repository open a
    PyMySQL connection; unit tests can supply a standard DB-API fake instead.
    """

    def __init__(
        self,
        config: MySQLConfig | None = None,
        *,
        connection: Any | None = None,
        connect: Callable[[], Any] | None = None,
    ) -> None:
        if connection is not None and connect is not None:
            raise ValueError("provide either connection or connect, not both")
        self._owned_connection = connection is None
        if connection is not None:
            self.connection = connection
        elif connect is not None:
            self.connection = connect()
        else:
            if config is None:
                raise ValueError("MySQL config, connection, or connect is required")
            self.connection = self._connect_pymysql(config)

    @staticmethod
    def _connect_pymysql(config: MySQLConfig) -> Any:
        try:
            import pymysql
        except ImportError as exc:  # pragma: no cover - requires deployment dependency
            raise RuntimeError("PyMySQL is required for MySQL storage") from exc
        return pymysql.connect(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.resolved_password,
            database=config.database,
            charset=config.charset,
            connect_timeout=config.connect_timeout,
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def __enter__(self) -> "MySQLPostRepository":
        self.initialize()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        self.close()

    def close(self) -> None:
        self.connection.close()

    def _execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cursor = self.connection.cursor()
        cursor.execute(sql, tuple(params))
        return cursor

    def _fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        cursor = self._execute(sql, params)
        row = cursor.fetchone()
        return self._as_dict(row, cursor) if row is not None else None

    def _fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cursor = self._execute(sql, params)
        return [self._as_dict(row, cursor) for row in cursor.fetchall()]

    @staticmethod
    def _as_dict(row: Any, cursor: Any) -> dict[str, Any]:
        if row is None:
            return {}
        if isinstance(row, Mapping):
            return dict(row)
        names = [column[0] for column in cursor.description]
        return dict(zip(names, row, strict=True))

    @staticmethod
    def _public_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
        """Keep X status identifiers stable across MySQL and SQLite adapters."""
        if row is None:
            return None
        result = dict(row)
        for name in ("post_id", "newest_seen_id", "oldest_seen_id"):
            if result.get(name) is not None:
                result[name] = str(result[name])
        return result

    def initialize(self) -> None:
        try:
            for statement in SCHEMA_STATEMENTS:
                self._execute(statement)
            row = self._fetchone("SELECT value FROM schema_meta WHERE `key` = %s", ("schema_version",))
            if row is None:
                self._execute(
                    "INSERT INTO schema_meta(`key`, value) VALUES (%s, %s)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
            elif int(row["value"]) != SCHEMA_VERSION:
                raise RuntimeError(
                    f"unsupported schema version {row['value']}; expected {SCHEMA_VERSION}"
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _ensure_account(
        self,
        handle: str,
        *,
        display_name: str = "",
        profile_url: str = "",
        seen_at: str | None = None,
    ) -> int:
        handle = normalize_handle(handle)
        if not handle:
            raise ValueError("account handle is required")
        seen_at = seen_at or utc_now()
        row = self._fetchone("SELECT account_id, display_name, profile_url FROM accounts WHERE handle = %s", (handle,))
        if row is None:
            cursor = self._execute(
                """INSERT INTO accounts(handle, display_name, profile_url, first_seen_at,
                   last_seen_at, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (handle, display_name, profile_url or None, seen_at, seen_at, seen_at, seen_at),
            )
            return int(cursor.lastrowid)
        self._execute(
            """UPDATE accounts SET display_name = %s, profile_url = %s,
               last_seen_at = %s, updated_at = %s WHERE account_id = %s""",
            (
                display_name or row["display_name"],
                profile_url or row["profile_url"],
                seen_at,
                seen_at,
                row["account_id"],
            ),
        )
        return int(row["account_id"])

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
        try:
            account_id = self._ensure_account(handle, seen_at=started_at)
            cursor = self._execute(
                """INSERT INTO crawl_runs(account_id, started_at, mode, requested_from, requested_until)
                VALUES (%s, %s, %s, %s, %s)""",
                (account_id, started_at, mode, requested_from, requested_until),
            )
            self.connection.commit()
            return int(cursor.lastrowid)
        except Exception:
            self.connection.rollback()
            raise

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
        try:
            row = self._fetchone("SELECT account_id FROM crawl_runs WHERE run_id = %s", (run_id,))
            if row is None:
                raise ValueError(f"unknown crawl run: {run_id}")
            self._execute(
                """UPDATE crawl_runs SET finished_at = %s, fetched_count = %s,
                   inserted_count = %s, updated_count = %s, unchanged_count = %s,
                   skipped_count = %s, error_count = %s, stop_reason = %s WHERE run_id = %s""",
                (finished_at, fetched_count, inserted_count, updated_count, unchanged_count,
                 skipped_count, error_count, stop_reason or None, run_id),
            )
            if successful:
                self._refresh_state(int(row["account_id"]), run_id, finished_at)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _refresh_state(self, account_id: int, run_id: int, updated_at: str) -> None:
        newest = self._fetchone(
            """SELECT p.created_at, p.post_id FROM posts p JOIN account_posts ap
            ON ap.post_id = p.post_id WHERE ap.account_id = %s
            ORDER BY p.created_epoch DESC, p.post_id DESC LIMIT 1""", (account_id,))
        oldest = self._fetchone(
            """SELECT p.created_at, p.post_id FROM posts p JOIN account_posts ap
            ON ap.post_id = p.post_id WHERE ap.account_id = %s
            ORDER BY p.created_epoch ASC, p.post_id ASC LIMIT 1""", (account_id,))
        existing = self._fetchone("SELECT account_id FROM crawl_state WHERE account_id = %s", (account_id,))
        values = (newest.get("created_at") if newest else None, newest.get("post_id") if newest else None,
                  oldest.get("created_at") if oldest else None, oldest.get("post_id") if oldest else None,
                  run_id, updated_at, account_id)
        if existing is None:
            self._execute(
                """INSERT INTO crawl_state(account_id, newest_seen_at, newest_seen_id,
                oldest_seen_at, oldest_seen_id, last_successful_run_id, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (account_id, *values[:-1]),
            )
        else:
            self._execute(
                """UPDATE crawl_state SET newest_seen_at = %s, newest_seen_id = %s,
                oldest_seen_at = %s, oldest_seen_id = %s, last_successful_run_id = %s,
                updated_at = %s WHERE account_id = %s""", values)

    def upsert_posts(
        self,
        posts: Iterable[Post | dict[str, Any]],
        *,
        handle: str,
        captured_at: str | None = None,
        relation: str = "own_post",
    ) -> dict[str, int]:
        captured_at = captured_at or utc_now()
        target_handle = normalize_handle(handle)
        counts = {"fetched": 0, "inserted": 0, "updated": 0, "unchanged": 0, "skipped": 0}
        try:
            self._execute("BEGIN")
            account_id = self._ensure_account(target_handle, seen_at=captured_at)
            refreshed_name = False
            for value in posts:
                counts["fetched"] += 1
                try:
                    post = value if isinstance(value, Post) else Post.from_mapping(value, target_handle)
                except (TypeError, ValueError):
                    counts["skipped"] += 1
                    continue
                if not refreshed_name and post.author_handle == target_handle and post.author_display_name:
                    self._ensure_account(target_handle, display_name=post.author_display_name,
                                         profile_url=f"https://x.com/{target_handle}", seen_at=captured_at)
                    refreshed_name = True
                existing = self._fetchone("SELECT content_hash FROM posts WHERE post_id = %s", (post.post_id,))
                if existing is None:
                    self._execute(
                        """INSERT INTO posts(post_id, url, created_at, created_epoch, text, author_handle,
                        author_display_name, post_kind, has_video, is_pinned, content_hash, raw_json,
                        first_seen_at, last_seen_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s)""",
                        self._post_values(post, captured_at),
                    )
                    counts["inserted"] += 1
                elif existing["content_hash"] == post.content_hash:
                    self._execute("UPDATE posts SET last_seen_at = %s, updated_at = %s WHERE post_id = %s",
                                  (captured_at, captured_at, post.post_id))
                    counts["unchanged"] += 1
                else:
                    self._execute(
                        """UPDATE posts SET url = %s, created_at = %s, created_epoch = %s, text = %s,
                        author_handle = %s, author_display_name = %s, post_kind = %s, has_video = %s,
                        is_pinned = %s, content_hash = %s, raw_json = %s, last_seen_at = %s, updated_at = %s
                        WHERE post_id = %s""",
                        (*self._post_values(post, captured_at)[1:12], captured_at, captured_at, post.post_id),
                    )
                    counts["updated"] += 1
                self._upsert_account_post(account_id, post.post_id, relation, captured_at)
                self._replace_media(post, captured_at)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return counts

    @staticmethod
    def _post_values(post: Post, captured_at: str) -> tuple[Any, ...]:
        return (post.post_id, post.url, post.created_at, post.created_epoch, post.text, post.author_handle,
                post.author_display_name, post.post_kind, int(post.has_video), int(post.is_pinned),
                post.content_hash, post.raw_json, captured_at, captured_at, captured_at)

    def _upsert_account_post(self, account_id: int, post_id: str, relation: str, captured_at: str) -> None:
        row = self._fetchone("SELECT account_id FROM account_posts WHERE account_id = %s AND post_id = %s",
                             (account_id, post_id))
        if row is None:
            self._execute("""INSERT INTO account_posts(account_id, post_id, relation, first_seen_at, last_seen_at)
                         VALUES (%s, %s, %s, %s, %s)""", (account_id, post_id, relation, captured_at, captured_at))
        else:
            self._execute("UPDATE account_posts SET relation = %s, last_seen_at = %s WHERE account_id = %s AND post_id = %s",
                          (relation, captured_at, account_id, post_id))

    def _replace_media(self, post: Post, captured_at: str) -> None:
        seen_ordinals: list[int] = []
        for item in post.media:
            seen_ordinals.append(item.ordinal)
            existing = self._fetchone("SELECT remote_url, state, retry_count, local_path FROM media WHERE post_id = %s AND ordinal = %s",
                                      (post.post_id, item.ordinal))
            if existing is None:
                self._execute(
                    """INSERT INTO media(post_id, ordinal, media_type, remote_url, alt_text, local_path,
                    width, height, state, retry_count, created_at, updated_at) VALUES (%s, %s, %s, %s, %s,
                    %s, %s, %s, 'pending', 0, %s, %s)""",
                    (post.post_id, item.ordinal, item.media_type, item.remote_url, item.alt_text,
                     item.local_path, item.width, item.height, captured_at, captured_at),
                )
            elif existing["remote_url"] == item.remote_url:
                self._execute("""UPDATE media SET media_type = %s, alt_text = %s, local_path = COALESCE(%s, local_path),
                width = %s, height = %s, updated_at = %s WHERE post_id = %s AND ordinal = %s""",
                              (item.media_type, item.alt_text, item.local_path, item.width, item.height,
                               captured_at, post.post_id, item.ordinal))
            else:
                self._execute("""UPDATE media SET media_type = %s, remote_url = %s, alt_text = %s,
                local_path = %s, width = %s, height = %s, state = 'pending', retry_count = 0,
                last_error = NULL, next_retry_at = NULL, content_type = NULL, content_sha256 = NULL,
                byte_size = NULL, updated_at = %s WHERE post_id = %s AND ordinal = %s""",
                              (item.media_type, item.remote_url, item.alt_text, item.local_path, item.width,
                               item.height, captured_at, post.post_id, item.ordinal))
        if seen_ordinals:
            placeholders = ", ".join("%s" for _ in seen_ordinals)
            self._execute(f"DELETE FROM media WHERE post_id = %s AND ordinal NOT IN ({placeholders})",
                          (post.post_id, *seen_ordinals))
        else:
            self._execute("DELETE FROM media WHERE post_id = %s", (post.post_id,))

    def get_state(self, handle: str) -> dict[str, Any] | None:
        return self._public_row(self._fetchone(
            """SELECT a.handle, cs.newest_seen_at, cs.newest_seen_id, cs.oldest_seen_at,
            cs.oldest_seen_id, cs.last_successful_run_id, cs.updated_at FROM accounts a
            JOIN crawl_state cs ON cs.account_id = a.account_id WHERE a.handle = %s""",
            (normalize_handle(handle),),
        ))

    def query_posts(self, *, handle: str | None = None, after: str | None = None,
                    after_id: str | None = None, before: str | None = None,
                    before_id: str | None = None, contains: str | None = None,
                    order: str = "asc", limit: int = 100) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        joins = ""
        if handle:
            joins = "JOIN account_posts ap ON ap.post_id = p.post_id JOIN accounts a ON a.account_id = ap.account_id"
            clauses.append("a.handle = %s")
            params.append(normalize_handle(handle))
        if after:
            _, epoch = normalize_timestamp(after)
            clauses.append("(p.created_epoch > %s OR (p.created_epoch = %s AND p.post_id > %s))")
            params.extend((epoch, epoch, after_id or "0"))
        if before:
            _, epoch = normalize_timestamp(before)
            clauses.append("(p.created_epoch < %s OR (p.created_epoch = %s AND p.post_id < %s))")
            params.extend((epoch, epoch, before_id or "18446744073709551615"))
        if contains:
            clauses.append("p.text LIKE %s")
            params.append(f"%{contains}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        direction = "DESC" if order.lower() == "desc" else "ASC"
        params.append(max(1, min(int(limit), 10000)))
        return [self._public_row(row) or {} for row in self._fetchall(
            f"""SELECT p.post_id, p.url, p.created_at, p.text, p.author_handle, p.author_display_name,
            p.post_kind, p.has_video, p.is_pinned, p.first_seen_at, p.last_seen_at, p.obsidian_path
            FROM posts p {joins} {where} ORDER BY p.created_epoch {direction}, p.post_id {direction} LIMIT %s""", params)]

    def get_media(self, post_id: str) -> list[dict[str, Any]]:
        return self._fetchall(
            """SELECT ordinal, media_type, remote_url, alt_text, local_path, width, height, state,
            retry_count, last_error, next_retry_at, content_type, content_sha256, byte_size
            FROM media WHERE post_id = %s ORDER BY ordinal ASC""", (post_id,))

    def list_retryable_media(self, *, limit: int = 100, max_retries: int = 3) -> list[dict[str, Any]]:
        return [self._public_row(row) or {} for row in self._fetchall(
            """SELECT post_id, ordinal, remote_url, retry_count FROM media
            WHERE state IN ('pending', 'failed') AND retry_count < %s
            AND (next_retry_at IS NULL OR next_retry_at <= %s)
            ORDER BY updated_at ASC LIMIT %s""", (max_retries, utc_now(), max(1, min(limit, 10000))))]

    def list_pending_media(self, *, limit: int = 1000) -> list[dict[str, Any]]:
        """Return downloader-shaped rows for pending/failed image media."""
        return self._fetchall(
            """SELECT m.media_id, m.post_id, m.ordinal, m.remote_url, m.retry_count,
            p.created_at, p.author_handle FROM media m JOIN posts p ON p.post_id = m.post_id
            WHERE m.state IN ('pending', 'failed') AND m.retry_count < 3
            ORDER BY m.updated_at ASC LIMIT %s""",
            (max(1, min(int(limit), 10000)),),
        )

    def mark_media_ready(self, media_id: int, *, local_path: str, sha256: str,
                         size_bytes: int, mime_type: str) -> None:
        self._execute(
            """UPDATE media SET state = 'ready', local_path = %s, content_sha256 = %s,
            byte_size = %s, content_type = %s, last_error = NULL, next_retry_at = NULL,
            updated_at = %s WHERE media_id = %s""",
            (local_path, sha256, size_bytes, mime_type, utc_now(), media_id),
        )
        self.connection.commit()

    def mark_media_failed(self, media_id: int, *, error: str) -> None:
        row = self._fetchone("SELECT post_id, ordinal FROM media WHERE media_id = %s", (media_id,))
        if row is None:
            raise ValueError(f"unknown media id: {media_id}")
        self.update_media_state(str(row["post_id"]), int(row["ordinal"]), state="failed", error=error)

    def update_media_state(self, post_id: str, ordinal: int, *, state: str,
                           local_path: str | Path | None = None, error: str | None = None,
                           content_type: str | None = None, content_sha256: str | None = None,
                           byte_size: int | None = None, next_retry_at: str | None = None) -> None:
        if state not in {"pending", "ready", "failed"}:
            raise ValueError("media state must be pending, ready, or failed")
        row = self._fetchone("SELECT retry_count FROM media WHERE post_id = %s AND ordinal = %s", (post_id, ordinal))
        if row is None:
            raise ValueError(f"unknown media: {post_id}/{ordinal}")
        retries = int(row["retry_count"]) + (1 if state == "failed" else 0)
        self._execute(
            """UPDATE media SET state = %s, local_path = COALESCE(%s, local_path), retry_count = %s,
            last_error = %s, next_retry_at = %s, content_type = COALESCE(%s, content_type),
            content_sha256 = COALESCE(%s, content_sha256), byte_size = COALESCE(%s, byte_size),
            updated_at = %s WHERE post_id = %s AND ordinal = %s""",
            (state, str(local_path) if local_path is not None else None, retries, error, next_retry_at,
             content_type, content_sha256, byte_size, utc_now(), post_id, ordinal),
        )
        self.connection.commit()

    def enqueue_candidate(self, handle: str, post_id: str, url: str, *, discovered_at: str | None = None,
                          raw_json: str | None = None) -> None:
        if not str(post_id).isdigit():
            raise ValueError("candidate post_id must be numeric")
        now = discovered_at or utc_now()
        try:
            account_id = self._ensure_account(handle, seen_at=now)
            existing = self._fetchone("SELECT status, raw_json FROM post_candidates WHERE account_id = %s AND post_id = %s",
                                      (account_id, post_id))
            if existing is None:
                self._execute(
                    """INSERT INTO post_candidates(account_id, post_id, url, discovered_at, last_seen_at,
                    status, raw_json, updated_at) VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s)""",
                    (account_id, post_id, url, now, now, raw_json, now),
                )
            else:
                self._execute("""UPDATE post_candidates SET url = %s, last_seen_at = %s,
                raw_json = COALESCE(%s, raw_json), updated_at = %s WHERE account_id = %s AND post_id = %s""",
                              (url, now, raw_json, now, account_id, post_id))
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def list_candidates(self, handle: str, *, statuses: Sequence[str] = ("pending", "error"),
                        limit: int = 100) -> list[dict[str, Any]]:
        allowed = tuple(statuses)
        if not allowed:
            return []
        placeholders = ", ".join("%s" for _ in allowed)
        return [self._public_row(row) or {} for row in self._fetchall(
            f"""SELECT pc.post_id, pc.url, pc.status, pc.attempts, pc.last_error, pc.raw_json,
            pc.discovered_at, pc.last_seen_at, pc.resolved_at FROM post_candidates pc
            JOIN accounts a ON a.account_id = pc.account_id WHERE a.handle = %s
            AND pc.status IN ({placeholders}) ORDER BY pc.discovered_at ASC, pc.post_id ASC LIMIT %s""",
            (normalize_handle(handle), *allowed, max(1, min(int(limit), 10000))),
        )]

    def mark_candidate(self, handle: str, post_id: str, *, status: str, error: str | None = None,
                       raw_json: str | None = None, resolved_at: str | None = None) -> None:
        valid = {"pending", "saved", "reply", "quote", "repost", "video", "other", "error"}
        if status not in valid:
            raise ValueError(f"invalid candidate status: {status}")
        account = self._fetchone("SELECT account_id FROM accounts WHERE handle = %s", (normalize_handle(handle),))
        if account is None:
            raise ValueError(f"unknown candidate account: {handle}")
        existing = self._fetchone("SELECT post_id FROM post_candidates WHERE account_id = %s AND post_id = %s",
                                  (account["account_id"], post_id))
        if existing is None:
            raise ValueError(f"unknown candidate: {post_id}")
        now = utc_now()
        self._execute(
            """UPDATE post_candidates SET status = %s, attempts = attempts + 1, last_error = %s,
            raw_json = COALESCE(%s, raw_json), resolved_at = %s, updated_at = %s
            WHERE account_id = %s AND post_id = %s""",
            (status, error, raw_json, resolved_at or (now if status not in {"pending", "error"} else None), now,
             account["account_id"], post_id),
        )
        self.connection.commit()

    def set_obsidian_path(self, post_id: str, path: str | Path | None) -> None:
        self._execute("UPDATE posts SET obsidian_path = %s, updated_at = %s WHERE post_id = %s",
                      (str(path) if path is not None else None, utc_now(), post_id))
        self.connection.commit()
