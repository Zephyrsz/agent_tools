#!/usr/bin/env python3
"""Fast Hugging Face model downloader with aria2 as the default backend.

Examples:
  # Download a complete model repository.
  python download_tools/download_hf_model.py owner/model \
    --local-dir /data/models/model

  # Download one file from a repository.
  python download_tools/download_hf_model.py owner/model model.gguf \
    --output /data/models/model.gguf

  # Use huggingface_hub instead of aria2.
  python download_tools/download_hf_model.py owner/model \
    --local-dir /data/models/model --backend hf
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import NamedTuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlparse
from urllib.request import Request, getproxies, urlopen


# Must be set before importing huggingface_hub so its transfer backend sees it.
os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


class HfTarget(NamedTuple):
    repo_id: str
    filename: str
    revision: str


class RepoFile(NamedTuple):
    path: str
    size: int | None


def parse_hf_url(url: str) -> HfTarget:
    """Parse https://huggingface.co/{repo}/resolve/{revision}/{path}."""
    parsed = urlparse(url)
    if parsed.netloc != "huggingface.co":
        raise ValueError(f"not a huggingface.co URL: {url}")

    parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
    if "resolve" not in parts:
        raise ValueError("URL must contain /resolve/{revision}/{filename}")

    resolve_index = parts.index("resolve")
    if resolve_index < 1 or resolve_index + 2 >= len(parts):
        raise ValueError("URL must look like /{repo_id}/resolve/{revision}/{filename}")

    repo_id = "/".join(parts[:resolve_index])
    revision = parts[resolve_index + 1]
    filename = "/".join(parts[resolve_index + 2 :])
    return HfTarget(repo_id=repo_id, filename=filename, revision=revision)


def is_snapshot_source(source: str, filename: str | None) -> bool:
    return filename is None and "://" not in source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download a Hugging Face model repository or one file. "
            "aria2 is the default download backend."
        )
    )
    parser.add_argument(
        "source",
        help="Hugging Face model repo_id or a huggingface.co resolve URL.",
    )
    parser.add_argument(
        "filename",
        nargs="?",
        help=(
            "Optional file path inside the repository. When omitted for a repo_id, "
            "the complete repository is downloaded."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Final output path in single-file mode.",
    )
    parser.add_argument(
        "-r",
        "--revision",
        default="main",
        help="Git revision, branch, or tag. Default: main.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Optional Hugging Face cache directory for the hf backend.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"),
        help="Hugging Face token. Defaults to HF_TOKEN/HUGGING_FACE_HUB_TOKEN.",
    )
    parser.add_argument(
        "--local-dir",
        type=Path,
        help=(
            "Output directory for a repository snapshot. Defaults to the model "
            "name. In single-file hf mode it is the temporary local_dir."
        ),
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Include a repository glob. May be repeated. Default: all files.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Exclude a repository glob. May be repeated.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=8,
        help="Concurrent repository file downloads. Default: 8.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matching repository files without downloading them.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redownload files even when complete output files already exist.",
    )
    parser.add_argument(
        "--backend",
        choices=("aria2", "hf"),
        default="aria2",
        help="Download backend. Default: aria2.",
    )
    parser.add_argument(
        "--connections",
        type=int,
        default=16,
        help="aria2 connections per file. Default: 16.",
    )
    parser.add_argument(
        "--proxy",
        help=(
            "Proxy URL passed to aria2. Defaults to HTTPS_PROXY/HTTP_PROXY or the "
            "operating system proxy settings."
        ),
    )
    args = parser.parse_args()

    snapshot_mode = is_snapshot_source(args.source, args.filename)
    if snapshot_mode:
        if args.output:
            parser.error("--output is only available for single-file downloads")
    else:
        if args.include:
            parser.error("--include is only available for repository downloads")
        if args.exclude:
            parser.error("--exclude is only available for repository downloads")
        if args.dry_run:
            parser.error("--dry-run is only available for repository downloads")

    if args.max_workers < 1:
        parser.error("--max-workers must be at least 1")
    if args.connections < 1:
        parser.error("--connections must be at least 1")
    return args


def get_target(args: argparse.Namespace) -> HfTarget:
    if args.filename:
        return HfTarget(repo_id=args.source, filename=args.filename, revision=args.revision)
    try:
        return parse_hf_url(args.source)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def ensure_huggingface_hub():
    try:
        from huggingface_hub import hf_hub_download  # type: ignore

        return hf_hub_download
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: huggingface_hub.\n"
            "Install the fast backend with:\n"
            "  python -m pip install -U 'huggingface_hub[hf_xet]'\n"
        ) from exc


def ensure_snapshot_download():
    try:
        from huggingface_hub import snapshot_download  # type: ignore

        return snapshot_download
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency: huggingface_hub.\n"
            "Install the fast backend with:\n"
            "  python -m pip install -U 'huggingface_hub[hf_xet]'\n"
        ) from exc


def ensure_aria2() -> str:
    aria2c = shutil.which("aria2c")
    if not aria2c:
        raise SystemExit("Missing dependency: aria2c. Install aria2 or use --backend hf.")
    return aria2c


def resolve_url(repo_id: str, revision: str, filename: str) -> str:
    return (
        f"https://huggingface.co/{quote(repo_id, safe='/')}/resolve/"
        f"{quote(revision, safe='')}/{quote(filename, safe='/')}"
    )


def source_url(args: argparse.Namespace, target: HfTarget) -> str:
    if args.filename:
        return resolve_url(target.repo_id, target.revision, target.filename)
    return args.source


def aria2_command(args: argparse.Namespace) -> list[str]:
    cmd = [
        ensure_aria2(),
        "--continue=true",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--file-allocation=none",
        "--max-connection-per-server",
        str(args.connections),
        "--split",
        str(args.connections),
        "--min-split-size=1M",
        "--max-tries=0",
        "--retry-wait=5",
        "--console-log-level=warn",
        "--summary-interval=10",
    ]
    if args.token:
        cmd.extend(["--header", f"Authorization: Bearer {args.token}"])
    proxies = getproxies()
    proxy = args.proxy or proxies.get("https") or proxies.get("http")
    if proxy:
        cmd.extend(["--all-proxy", proxy])
    return cmd


def download_with_aria2(args: argparse.Namespace, target: HfTarget, output: Path) -> None:
    control_file = output.with_name(output.name + ".aria2")
    if args.force:
        if output.is_dir():
            raise SystemExit(f"Output path is a directory: {output}")
        output.unlink(missing_ok=True)
        control_file.unlink(missing_ok=True)

    cmd = aria2_command(args)
    cmd.extend(["--dir", str(output.parent), "--out", output.name])
    cmd.append(source_url(args, target))

    print(f"Backend:  aria2c with {args.connections} connections")
    subprocess.run(cmd, check=True)


def _next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for item in link_header.split(","):
        fields = [field.strip() for field in item.split(";")]
        if len(fields) < 2 or 'rel="next"' not in fields[1:]:
            continue
        if fields[0].startswith("<") and fields[0].endswith(">"):
            return fields[0][1:-1]
    return None


def list_repo_files(repo_id: str, revision: str, token: str | None) -> list[RepoFile]:
    """List all files through the paginated Hugging Face model tree API."""
    url = (
        f"https://huggingface.co/api/models/{quote(repo_id, safe='/')}/tree/"
        f"{quote(revision, safe='')}?recursive=true&expand=false"
    )
    headers = {
        "Accept": "application/json",
        "User-Agent": "download-hf-model/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    files: list[RepoFile] = []
    try:
        while url:
            request = Request(url, headers=headers)
            with urlopen(request) as response:
                payload = json.load(response)
                next_url = _next_link(response.headers.get("Link"))
            if not isinstance(payload, list):
                raise SystemExit("Unexpected response from the Hugging Face tree API.")
            for item in payload:
                if not isinstance(item, dict) or item.get("type") != "file":
                    continue
                path = item.get("path")
                if not isinstance(path, str):
                    continue
                raw_size = item.get("size")
                size = raw_size if isinstance(raw_size, int) and raw_size >= 0 else None
                files.append(RepoFile(path=path, size=size))
            url = urljoin(url, next_url) if next_url else ""
    except HTTPError as exc:
        message = f"Hugging Face API request failed with HTTP {exc.code}"
        if exc.code in (401, 403):
            message += "; set HF_TOKEN if the model is private or gated"
        raise SystemExit(message) from exc
    except URLError as exc:
        raise SystemExit(f"Could not reach the Hugging Face API: {exc.reason}") from exc

    return sorted(files, key=lambda item: item.path)


def matches_patterns(path: str, includes: list[str], excludes: list[str]) -> bool:
    if includes and not any(fnmatch.fnmatchcase(path, pattern) for pattern in includes):
        return False
    return not any(fnmatch.fnmatchcase(path, pattern) for pattern in excludes)


def snapshot_output_path(local_dir: Path, repo_path: str) -> Path:
    if "\n" in repo_path or "\r" in repo_path:
        raise SystemExit(f"Unsupported repository filename: {repo_path!r}")
    parts = repo_path.split("/")
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise SystemExit(f"Unsafe repository filename: {repo_path!r}")
    return local_dir.joinpath(*parts)


def pending_aria2_files(
    args: argparse.Namespace, local_dir: Path, files: list[RepoFile]
) -> tuple[list[tuple[RepoFile, Path]], int]:
    pending: list[tuple[RepoFile, Path]] = []
    skipped = 0
    for repo_file in files:
        output = snapshot_output_path(local_dir, repo_file.path)
        control_file = output.with_name(output.name + ".aria2")
        if output.is_dir():
            raise SystemExit(f"File output path is already a directory: {output}")
        if args.force:
            if not args.dry_run:
                output.unlink(missing_ok=True)
                control_file.unlink(missing_ok=True)
        elif output.exists() and not control_file.exists():
            if repo_file.size is None or output.stat().st_size == repo_file.size:
                skipped += 1
                continue
        if not args.dry_run:
            output.parent.mkdir(parents=True, exist_ok=True)
        pending.append((repo_file, output))
    return pending, skipped


def print_snapshot_dry_run(
    files: list[RepoFile], pending_paths: set[str], skipped: int
) -> None:
    print()
    for repo_file in files:
        state = "download" if repo_file.path in pending_paths else "exists"
        size = "unknown" if repo_file.size is None else f"{repo_file.size / (1024**3):.3f} GiB"
        print(f"{state:8} {size:>13}  {repo_file.path}")
    known_size = sum(item.size or 0 for item in files)
    print(f"Files:    {len(files)} ({len(pending_paths)} pending, {skipped} existing)")
    print(f"Size:     {known_size / (1024**3):.2f} GiB known")


def download_snapshot_with_aria2(
    args: argparse.Namespace, local_dir: Path, files: list[RepoFile]
) -> int:
    pending, skipped = pending_aria2_files(args, local_dir, files)
    pending_paths = {item.path for item, _ in pending}
    if args.dry_run:
        print_snapshot_dry_run(files, pending_paths, skipped)
        return 0
    if not pending:
        print(f"Already complete: {local_dir}")
        print(f"Files:    {len(files)}")
        return 0

    aria2_input: Path | None = None
    started = time.monotonic()
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="hf-aria2-", suffix=".txt", delete=False
        ) as input_file:
            aria2_input = Path(input_file.name)
            for repo_file, output in pending:
                input_file.write(resolve_url(args.source, args.revision, repo_file.path) + "\n")
                input_file.write(f"  dir={output.parent}\n")
                input_file.write(f"  out={output.name}\n")

        cmd = aria2_command(args)
        cmd.extend(
            [
                "--max-concurrent-downloads",
                str(args.max_workers),
                "--input-file",
                str(aria2_input),
            ]
        )
        print(
            f"Backend:  aria2c, {args.max_workers} files in parallel, "
            f"{args.connections} connections per file"
        )
        subprocess.run(cmd, check=True)
    finally:
        if aria2_input:
            aria2_input.unlink(missing_ok=True)

    for repo_file, output in pending:
        if not output.is_file():
            raise SystemExit(f"Download did not create the expected file: {output}")
        if repo_file.size is not None and output.stat().st_size != repo_file.size:
            raise SystemExit(
                f"Downloaded size mismatch for {repo_file.path}: "
                f"expected {repo_file.size}, got {output.stat().st_size}"
            )

    elapsed = max(time.monotonic() - started, 0.001)
    downloaded_size = sum(output.stat().st_size for _, output in pending)
    total_size = sum((item.size or 0) for item in files)
    print(f"Done:     {local_dir}")
    print(f"Files:    {len(files)} ({len(pending)} downloaded, {skipped} existing)")
    print(f"Size:     {total_size / (1024**3):.2f} GiB known")
    print(f"Elapsed:  {elapsed:.1f}s")
    print(f"Average:  {downloaded_size / elapsed / (1024**2):.1f} MiB/s")
    return 0


def matched_snapshot_files(
    root: Path, includes: list[str], excludes: list[str]
) -> list[Path]:
    matches = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative.startswith(".cache/huggingface/"):
            continue
        if matches_patterns(relative, includes, excludes):
            matches.append(path)
    return matches


def download_snapshot_with_hf(args: argparse.Namespace, local_dir: Path) -> int:
    print("Backend:  huggingface_hub snapshot with HF_XET_HIGH_PERFORMANCE=1")
    snapshot_download = ensure_snapshot_download()
    options = {
        "repo_id": args.source,
        "revision": args.revision,
        "token": args.token,
        "cache_dir": str(args.cache_dir) if args.cache_dir else None,
        "local_dir": str(local_dir),
        "allow_patterns": args.include or None,
        "ignore_patterns": args.exclude or None,
        "force_download": args.force,
        "max_workers": args.max_workers,
    }

    if args.dry_run:
        results = snapshot_download(**options, dry_run=True)
        total_bytes = sum(item.file_size for item in results)
        download_bytes = sum(item.file_size for item in results if item.will_download)
        print()
        for item in results:
            state = "download" if item.will_download else "cached"
            size_gib = item.file_size / (1024**3)
            print(f"{state:8} {size_gib:8.3f} GiB  {item.filename}")
        print(f"Files:    {len(results)}")
        print(f"Size:     {total_bytes / (1024**3):.2f} GiB total")
        print(f"Pending:  {download_bytes / (1024**3):.2f} GiB")
        return 0

    started = time.monotonic()
    snapshot_path = Path(snapshot_download(**options)).resolve()
    elapsed = max(time.monotonic() - started, 0.001)
    files = matched_snapshot_files(snapshot_path, args.include, args.exclude)
    size_gib = sum(path.stat().st_size for path in files) / (1024**3)
    print(f"Done:     {snapshot_path}")
    print(f"Files:    {len(files)}")
    print(f"Size:     {size_gib:.2f} GiB")
    print(f"Elapsed:  {elapsed:.1f}s")
    return 0


def download_snapshot(args: argparse.Namespace) -> int:
    local_dir = (
        args.local_dir or Path(args.source.rstrip("/").rsplit("/", 1)[-1])
    ).expanduser().resolve()
    if not args.dry_run:
        local_dir.mkdir(parents=True, exist_ok=True)

    print(f"Repo:     {args.source}")
    print(f"Revision: {args.revision}")
    if args.include:
        print(f"Include:  {', '.join(args.include)}")
    if args.exclude:
        print(f"Exclude:  {', '.join(args.exclude)}")
    print(f"Output:   {local_dir}")

    if args.backend == "hf":
        return download_snapshot_with_hf(args, local_dir)

    files = [
        item
        for item in list_repo_files(args.source, args.revision, args.token)
        if matches_patterns(item.path, args.include, args.exclude)
    ]
    if not files:
        raise SystemExit("No repository files matched the requested patterns.")
    return download_snapshot_with_aria2(args, local_dir, files)


def download_single_file(args: argparse.Namespace) -> int:
    target = get_target(args)
    output = Path(args.output or Path(target.filename).name).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    aria2_control_file = output.with_name(output.name + ".aria2")
    if output.exists() and not args.force and not (
        args.backend == "aria2" and aria2_control_file.exists()
    ):
        print(f"Already exists: {output}")
        print("Use --force to redownload.")
        return 0

    local_dir = (args.local_dir or output.parent).expanduser().resolve()
    local_dir.mkdir(parents=True, exist_ok=True)

    print(f"Repo:     {target.repo_id}")
    print(f"Revision: {target.revision}")
    print(f"File:     {target.filename}")
    print(f"Output:   {output}")

    started = time.monotonic()
    if args.backend == "aria2":
        download_with_aria2(args, target, output)
    else:
        hf_hub_download = ensure_huggingface_hub()
        print("Backend:  huggingface_hub with HF_XET_HIGH_PERFORMANCE=1")
        downloaded_path = Path(
            hf_hub_download(
                repo_id=target.repo_id,
                filename=target.filename,
                revision=target.revision,
                token=args.token,
                cache_dir=str(args.cache_dir) if args.cache_dir else None,
                local_dir=str(local_dir),
                force_download=args.force,
            )
        ).resolve()

        if downloaded_path != output:
            if output.exists():
                output.unlink()
            shutil.move(str(downloaded_path), str(output))

    elapsed = max(time.monotonic() - started, 0.001)
    size_gib = output.stat().st_size / (1024**3)
    print(f"Done:     {output}")
    print(f"Size:     {size_gib:.2f} GiB")
    print(f"Elapsed:  {elapsed:.1f}s")
    print(f"Average:  {size_gib / elapsed * 1024:.1f} MiB/s")
    return 0


def main() -> int:
    args = parse_args()
    if is_snapshot_source(args.source, args.filename):
        return download_snapshot(args)
    return download_single_file(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Rerun the same command to resume.", file=sys.stderr)
        raise SystemExit(130)
