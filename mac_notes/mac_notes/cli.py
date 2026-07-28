"""Command-line interface for Apple Notes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .client import NotesClient, NotesError


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def add_location_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--account", help="Account name or account ID.")
    parser.add_argument("--folder", help="Folder name or full path.")
    parser.add_argument("--folder-id", help="Folder ID; avoids ambiguous names.")


def add_content_arguments(parser: argparse.ArgumentParser, *, required: bool) -> None:
    group = parser.add_mutually_exclusive_group(required=required)
    group.add_argument("--content", help="Inline note content.")
    group.add_argument(
        "--content-file",
        type=Path,
        help="Read note content from this UTF-8 file; use - for stdin.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "html"),
        default="text",
        dest="content_format",
        help="Interpret content as plain text or trusted HTML (default: text).",
    )


def read_content(args: argparse.Namespace) -> str:
    if args.content is not None:
        return args.content
    if args.content_file is None:
        return ""
    if str(args.content_file) == "-":
        return sys.stdin.read()
    try:
        return args.content_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise NotesError(
            f"Could not read content file {args.content_file}: {exc}",
            code="CONTENT_FILE_ERROR",
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mac-notes",
        description="Read and write the current user's Apple Notes on macOS.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="Check Notes access and show the default account.")

    accounts = subparsers.add_parser("accounts", help="List Apple Notes accounts.")
    accounts.set_defaults(command="accounts")

    folders = subparsers.add_parser("folders", help="List folders.")
    folders.add_argument("--account", help="Account name or account ID.")

    listing = subparsers.add_parser("list", help="List note metadata.")
    add_location_arguments(listing)
    listing.add_argument("--query", help="Case-insensitive title filter.")
    listing.add_argument("--recursive", action="store_true")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--offset", type=int, default=0)

    read = subparsers.add_parser("read", help="Read one note by ID.")
    read.add_argument("note_id")

    create = subparsers.add_parser("create", help="Create a note.")
    create.add_argument("--title", required=True)
    add_content_arguments(create, required=False)
    add_location_arguments(create)

    update = subparsers.add_parser("update", help="Replace or append note content.")
    update.add_argument("note_id")
    add_content_arguments(update, required=True)
    update.add_argument("--mode", choices=("replace", "append"), default="replace")
    update.add_argument(
        "--no-preserve-title",
        action="store_false",
        dest="preserve_title",
        help="Do not retain the existing title when replacing content.",
    )

    serve = subparsers.add_parser("serve", help="Start the localhost HTTP API.")
    serve.add_argument("--port", type=int, default=8766)
    serve.add_argument("--reload", action="store_true")
    return parser


def execute(args: argparse.Namespace, client: NotesClient) -> Any:
    if args.command == "health":
        return client.health()
    if args.command == "accounts":
        return client.list_accounts()
    if args.command == "folders":
        return client.list_folders(account=args.account)
    if args.command == "list":
        return client.list_notes(
            account=args.account,
            folder=args.folder,
            folder_id=args.folder_id,
            query=args.query,
            recursive=args.recursive,
            limit=args.limit,
            offset=args.offset,
        )
    if args.command == "read":
        return client.get_note(args.note_id)
    if args.command == "create":
        return client.create_note(
            title=args.title,
            content=read_content(args),
            content_format=args.content_format,
            account=args.account,
            folder=args.folder,
            folder_id=args.folder_id,
        )
    if args.command == "update":
        return client.update_note(
            args.note_id,
            read_content(args),
            mode=args.mode,
            content_format=args.content_format,
            preserve_title=args.preserve_title,
        )
    raise NotesError(f"Unknown command: {args.command}", code="INVALID_REQUEST")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "serve":
        if not 1 <= args.port <= 65535:
            parser.error("--port must be between 1 and 65535")
        import uvicorn

        uvicorn.run(
            "mac_notes.api:app",
            host="127.0.0.1",
            port=args.port,
            reload=args.reload,
        )
        return 0
    try:
        print_json(execute(args, NotesClient()))
        return 0
    except NotesError as exc:
        print_json({"error": {"code": exc.code, "message": str(exc)}})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
