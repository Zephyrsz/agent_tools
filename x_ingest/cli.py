"""Unified command line interface for the X ingestion project."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .analysis import analyze_author_dir
from .config import AppConfig, load_config
from .obsidian import export_posts
from .service import ingest_json
from .store import SQLitePostStore


def add_database(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--database", type=Path, help="Override the configured SQLite path."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m x_ingest", description="Archive X posts."
    )
    parser.add_argument("--config", type=Path, help="JSON configuration file.")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="Initialize the SQLite schema.")
    add_database(init)

    imp = sub.add_parser("import", help="Import extractor JSON idempotently.")
    imp.add_argument("json_file", type=Path)
    imp.add_argument(
        "--handle", help="Timeline handle; inferred from JSON when omitted."
    )
    imp.add_argument(
        "--mode", choices=("full", "incremental", "backfill"), default="incremental"
    )
    imp.add_argument("--relation", help="Timeline relation such as own_post or reply.")
    add_database(imp)

    query = sub.add_parser("query", help="Query posts as JSON lines.")
    query.add_argument("--handle")
    query.add_argument("--after")
    query.add_argument("--after-id", help="Post ID paired with --after.")
    query.add_argument("--before")
    query.add_argument("--before-id", help="Post ID paired with --before.")
    query.add_argument("--contains")
    query.add_argument("--order", choices=("asc", "desc"), default="asc")
    query.add_argument("--limit", type=int, default=100)
    add_database(query)

    state = sub.add_parser("state", help="Show successful incremental cursors.")
    state.add_argument("--handle", required=True)
    add_database(state)

    export = sub.add_parser("export", help="Export database posts to Obsidian.")
    export.add_argument("--handle", required=True)
    export.add_argument("--vault", type=Path)
    export.add_argument("--folder")
    export.add_argument("--after")
    export.add_argument("--after-id")
    export.add_argument("--before")
    export.add_argument("--before-id")
    export.add_argument("--limit", type=int, default=10000)
    add_database(export)

    analyze = sub.add_parser(
        "analyze", help="Analyze exported raw Markdown with an LLM."
    )
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


def database_path(args: argparse.Namespace, config: AppConfig) -> Path:
    return (args.database or config.database).expanduser().resolve()


def main() -> int:
    args = build_parser().parse_args()
    config = load_config(args.config)

    if args.command == "analyze":
        written = analyze_author_dir(
            args.author_dir,
            base_url=args.base_url,
            model=args.model,
            analysis_dir_name=args.analysis_dir_name,
            limit=args.limit,
            newest_first=args.newest_first,
            overwrite=args.overwrite,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        for path in written:
            print(path)
        return 0

    database = database_path(args, config)
    with SQLitePostStore(database) as store:
        if args.command == "init":
            print(database)
        elif args.command == "import":
            handle = args.handle or ""
            user = config.user(handle) if handle else None
            result = ingest_json(
                store,
                args.json_file,
                handle=handle,
                mode=args.mode,
                relation=args.relation or (user.relation if user else "own_post"),
            )
            print(json.dumps(result, ensure_ascii=False))
        elif args.command == "query":
            for post in store.query_posts(
                handle=args.handle,
                after=args.after,
                after_id=args.after_id,
                before=args.before,
                before_id=args.before_id,
                contains=args.contains,
                order=args.order,
                limit=args.limit,
            ):
                print(json.dumps(post, ensure_ascii=False))
        elif args.command == "state":
            print(
                json.dumps(store.get_state(args.handle), ensure_ascii=False, indent=2)
            )
        elif args.command == "export":
            vault = args.vault or config.vault
            if vault is None:
                raise SystemExit("Obsidian vault is required in config or --vault")
            paths = export_posts(
                store,
                vault=vault,
                handle=args.handle,
                folder=args.folder or config.obsidian_folder,
                after=args.after,
                after_id=args.after_id,
                before=args.before,
                before_id=args.before_id,
                limit=args.limit,
            )
            for path in paths:
                print(path)
    return 0
