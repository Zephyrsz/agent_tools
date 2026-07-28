#!/usr/bin/env python3
"""Fast Hugging Face single-file downloader.

Examples:
  python scripts/download_hf_model.py \
    "https://huggingface.co/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive/resolve/main/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf" \
    --output /home/ubuntu/data/models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q8_K_P.gguf

  HF_TOKEN=hf_xxx python scripts/download_hf_model.py owner/repo model.gguf
"""

from __future__ import annotations

import argparse
import os
import subprocess
import shutil
import sys
import time
from pathlib import Path
from typing import NamedTuple
from urllib.parse import unquote, urlparse


# Must be set before importing huggingface_hub so its transfer backend sees it.
os.environ.setdefault("HF_XET_HIGH_PERFORMANCE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


class HfTarget(NamedTuple):
    repo_id: str
    filename: str
    revision: str


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download one large file from Hugging Face as fast as the installed "
            "transfer backend allows."
        )
    )
    parser.add_argument(
        "source",
        help=(
            "Hugging Face resolve URL, or repo_id when a second filename argument "
            "is provided."
        ),
    )
    parser.add_argument(
        "filename",
        nargs="?",
        help="File path inside the repo, used only when source is a repo_id.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Final output file path. Defaults to the Hugging Face filename basename.",
    )
    parser.add_argument(
        "-r",
        "--revision",
        default="main",
        help="Git revision/branch/tag when source is a repo_id. Default: main.",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        help="Optional Hugging Face cache directory.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN"),
        help="Hugging Face token. Defaults to HF_TOKEN/HUGGING_FACE_HUB_TOKEN env vars.",
    )
    parser.add_argument(
        "--local-dir",
        type=Path,
        help=(
            "Directory for Hugging Face local_dir downloads. Defaults to the output "
            "parent, which avoids a second large file copy."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redownload even if the output path already exists.",
    )
    parser.add_argument(
        "--backend",
        choices=("hf", "aria2"),
        default="hf",
        help="Download backend. Use aria2 for direct multi-connection URL downloads.",
    )
    parser.add_argument(
        "--connections",
        type=int,
        default=16,
        help="aria2 connection count per server when --backend aria2 is used.",
    )
    return parser.parse_args()


def get_target(args: argparse.Namespace) -> HfTarget:
    if args.filename:
        return HfTarget(repo_id=args.source, filename=args.filename, revision=args.revision)
    return parse_hf_url(args.source)


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


def source_url(args: argparse.Namespace, target: HfTarget) -> str:
    if args.filename:
        return (
            "https://huggingface.co/"
            f"{target.repo_id}/resolve/{target.revision}/{target.filename}"
        )
    return args.source


def download_with_aria2(args: argparse.Namespace, target: HfTarget, output: Path) -> None:
    aria2c = shutil.which("aria2c")
    if not aria2c:
        raise SystemExit("Missing dependency: aria2c. Install aria2 or use --backend hf.")

    if output.exists() and args.force:
        output.unlink()

    cmd = [
        aria2c,
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
        "--summary-interval=10",
        "--dir",
        str(output.parent),
        "--out",
        output.name,
    ]
    if args.token:
        cmd.extend(["--header", f"Authorization: Bearer {args.token}"])
    cmd.append(source_url(args, target))

    print(f"Backend:  aria2c with {args.connections} connections")
    subprocess.run(cmd, check=True)


def main() -> int:
    args = parse_args()
    target = get_target(args)

    output = args.output or Path(target.filename).name
    output = Path(output).expanduser().resolve()
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


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nInterrupted. Rerun the same command to resume.", file=sys.stderr)
        raise SystemExit(130)
