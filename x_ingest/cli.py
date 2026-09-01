"""Command line interface for MySQL-backed X ingestion."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from .analysis import analyze_author_dir
from .browser_gateway import ChromeDevToolsMcpGateway
from .config import AppConfig, load_config
from .crawler import CrawlCoordinator
from .media import MediaDownloader
from .mysql_store import MySQLPostRepository
from .obsidian import export_posts
from .service import ingest_json
from .store import SQLitePostStore


def add_storage(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--storage", choices=("mysql", "sqlite"), default="mysql",
        help="Persistence adapter (MySQL by default; SQLite is offline compatibility only).",
    )
    parser.add_argument("--database", type=Path, help="SQLite path when --storage sqlite is selected.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m x_ingest", description="Archive original X posts.")
    parser.add_argument("--config", type=Path, help="JSON configuration file.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize the configured schema.")
    add_storage(init)
    login = sub.add_parser("login", help="Wait for X authentication in the dedicated Chrome profile.")
    login.add_argument("--timeout", type=float, default=300.0)
    crawl = sub.add_parser("crawl", help="Discover candidates and archive original details.")
    crawl.add_argument("--handle")
    crawl.add_argument("--mode", choices=("incremental", "full", "backfill"), default="incremental")
    crawl.add_argument("--limit", type=int)
    crawl.add_argument("--from", dest="requested_from")
    crawl.add_argument("--until", dest="requested_until")
    retry = sub.add_parser("retry-media", help="Retry pending or failed image downloads.")
    retry.add_argument("--limit", type=int, default=1000)

    imp = sub.add_parser("import", help="Import extractor JSON idempotently.")
    imp.add_argument("json_file", type=Path)
    imp.add_argument("--handle")
    imp.add_argument("--mode", choices=("full", "incremental", "backfill"), default="incremental")
    imp.add_argument("--relation")
    add_storage(imp)
    query = sub.add_parser("query", help="Query canonical posts as JSON lines.")
    query.add_argument("--handle")
    query.add_argument("--after")
    query.add_argument("--after-id")
    query.add_argument("--before")
    query.add_argument("--before-id")
    query.add_argument("--contains")
    query.add_argument("--order", choices=("asc", "desc"), default="asc")
    query.add_argument("--limit", type=int, default=100)
    add_storage(query)
    state = sub.add_parser("state", help="Show successful crawl cursors.")
    state.add_argument("--handle", required=True)
    add_storage(state)
    export = sub.add_parser("export", help="Export canonical posts to Obsidian Markdown.")
    export.add_argument("--handle", required=True)
    export.add_argument("--vault", type=Path)
    export.add_argument("--folder")
    export.add_argument("--after")
    export.add_argument("--after-id")
    export.add_argument("--before")
    export.add_argument("--before-id")
    export.add_argument("--limit", type=int, default=10000)
    add_storage(export)
    analyze = sub.add_parser("analyze", help="Analyze exported raw Markdown with an LLM.")
    analyze.add_argument("--author-dir", required=True, type=Path)
    analyze.add_argument("--base-url", default="http://thor:8000/")
    analyze.add_argument("--model", default="qwen35b")
    analyze.add_argument("--analysis-dir-name", default="analysis")
    analyze.add_argument("--limit", type=int)
    analyze.add_argument("--newest-first", action="store_true")
    analyze.add_argument("--overwrite", action="store_true")
    analyze.add_argument("--temperature", type=float, default=0.2)
    analyze.add_argument("--max-tokens", type=int, default=1600)
    return parser


def _sqlite_path(args: argparse.Namespace, config: AppConfig) -> Path:
    if args.storage != "sqlite":
        raise SystemExit("SQLite is offline compatibility only; pass --storage sqlite explicitly")
    return (args.database or config.database).expanduser().resolve()


def _repository(args: argparse.Namespace, config: AppConfig) -> Any:
    if args.storage == "sqlite":
        return SQLitePostStore(_sqlite_path(args, config))
    return MySQLPostRepository(config.mysql)


def _run_async(coro: Any) -> Any:
    return asyncio.run(coro)


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)
    if args.command == "analyze":
        for path in analyze_author_dir(
            args.author_dir, base_url=args.base_url, model=args.model,
            analysis_dir_name=args.analysis_dir_name, limit=args.limit,
            newest_first=args.newest_first, overwrite=args.overwrite,
            temperature=args.temperature, max_tokens=args.max_tokens,
        ):
            print(path)
        return 0
    if args.command == "login":
        gateway = ChromeDevToolsMcpGateway(config)
        async def login_and_close() -> dict[str, Any]:
            try:
                return await gateway.login(timeout=args.timeout)
            finally:
                await gateway.close()
        result = _run_async(login_and_close())
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("authenticated") else 1
    if args.command == "crawl":
        handles = [args.handle] if args.handle else [u.handle for u in config.users.values() if u.enabled]
        if not handles:
            raise SystemExit("crawl handle is required or users must be enabled in config")

        async def run_crawls() -> list[dict[str, Any]]:
            repository = MySQLPostRepository(config.mysql)
            repository.initialize()
            gateway = ChromeDevToolsMcpGateway(config)
            try:
                return [await CrawlCoordinator(repository, gateway).crawl(
                    handle, mode=args.mode, limit=args.limit,
                    requested_from=args.requested_from, requested_until=args.requested_until,
                ) for handle in handles]
            finally:
                repository.close()

        for result in _run_async(run_crawls()):
            print(json.dumps(result, ensure_ascii=False))
        return 0
    if args.command == "retry-media":
        repository = MySQLPostRepository(config.mysql)
        try:
            repository.initialize()
            result = MediaDownloader(repository, config.media_root, max_retries=config.browser.max_retries).retry_pending(limit=args.limit)
            print(json.dumps(result, ensure_ascii=False))
        finally:
            repository.close()
        return 0
    repository = _repository(args, config)
    with repository:
        repository.initialize()
        if args.command == "init":
            print("mysql" if args.storage == "mysql" else _sqlite_path(args, config))
        elif args.command == "import":
            user = config.user(args.handle) if args.handle else None
            result = ingest_json(repository, args.json_file, handle=args.handle or "", mode=args.mode,
                                 relation=args.relation or (user.relation if user else "own_post"))
            print(json.dumps(result, ensure_ascii=False))
        elif args.command == "query":
            for post in repository.query_posts(handle=args.handle, after=args.after, after_id=args.after_id,
                                               before=args.before, before_id=args.before_id,
                                               contains=args.contains, order=args.order, limit=args.limit):
                print(json.dumps(post, ensure_ascii=False))
        elif args.command == "state":
            print(json.dumps(repository.get_state(args.handle), ensure_ascii=False, indent=2))
        elif args.command == "export":
            vault = args.vault or config.vault
            if vault is None:
                raise SystemExit("Obsidian vault is required in config or --vault")
            for path in export_posts(repository, vault=vault, handle=args.handle,
                                     folder=args.folder or config.obsidian_folder,
                                     after=args.after, after_id=args.after_id,
                                     before=args.before, before_id=args.before_id, limit=args.limit):
                print(path)
    return 0
