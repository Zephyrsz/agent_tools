"""Canonical data model shared by extractors, storage, and exporters."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


STATUS_ID_RE = re.compile(r"/status/(\d+)")


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def normalize_handle(value: str) -> str:
    return str(value or "").strip().lstrip("@").lower()


def post_id_from_url(url: str) -> str:
    match = STATUS_ID_RE.search(str(url or ""))
    return match.group(1) if match else ""


def normalize_timestamp(value: str) -> tuple[str, int]:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("post timestamp is required")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.strptime(raw, "%a %b %d %H:%M:%S %z %Y")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    canonical = parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return canonical, int(parsed.timestamp() * 1000)


@dataclass(frozen=True)
class MediaItem:
    ordinal: int
    remote_url: str
    media_type: str = "image"
    alt_text: str = ""
    local_path: str | None = None
    width: int | None = None
    height: int | None = None

    @classmethod
    def from_value(cls, value: Any, ordinal: int) -> "MediaItem | None":
        if isinstance(value, str):
            url = value.strip()
            return cls(ordinal=ordinal, remote_url=url) if url else None
        if not isinstance(value, Mapping):
            return None
        url = str(value.get("url", "")).strip()
        if not url:
            return None
        return cls(
            ordinal=ordinal,
            remote_url=url,
            media_type=str(value.get("type", value.get("mediaType", "image")))
            .strip()
            .lower()
            or "image",
            alt_text=str(value.get("alt", value.get("altText", ""))).strip(),
            local_path=str(value["localPath"]).strip()
            if value.get("localPath")
            else None,
            width=int(value["width"]) if value.get("width") is not None else None,
            height=int(value["height"]) if value.get("height") is not None else None,
        )


@dataclass(frozen=True)
class Post:
    post_id: str
    url: str
    created_at: str
    created_epoch: int
    text: str
    author_handle: str
    author_display_name: str
    post_kind: str
    has_video: bool
    is_pinned: bool
    media: tuple[MediaItem, ...]
    raw_json: str
    content_hash: str

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any], fallback_handle: str = ""
    ) -> "Post":
        raw = dict(value)
        url = str(raw.get("url", "")).strip()
        post_id = str(raw.get("postId") or raw.get("statusId") or "").strip()
        post_id = post_id or post_id_from_url(url)
        if not post_id or not post_id.isdigit():
            raise ValueError("post URL or postId must contain a numeric status ID")
        if not url:
            url = f"https://x.com/i/status/{post_id}"

        created_at, created_epoch = normalize_timestamp(str(raw.get("timestamp", "")))
        author = raw.get("author") if isinstance(raw.get("author"), Mapping) else {}
        author_handle = normalize_handle(
            str(author.get("handle", ""))
        ) or normalize_handle(fallback_handle)
        if not author_handle:
            raise ValueError("post author handle is required")
        media_values = raw.get("images") if isinstance(raw.get("images"), list) else []
        media = tuple(
            item
            for index, media_value in enumerate(media_values, start=1)
            if (item := MediaItem.from_value(media_value, index)) is not None
        )
        raw_json = json.dumps(
            raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return cls(
            post_id=post_id,
            url=url,
            created_at=created_at,
            created_epoch=created_epoch,
            text=str(raw.get("text", "")).strip(),
            author_handle=author_handle,
            author_display_name=str(author.get("displayName", "")).strip(),
            post_kind=str(raw.get("postKind", raw.get("type", "post"))).strip()
            or "post",
            has_video=bool(raw.get("hasVideo")),
            is_pinned=bool(raw.get("pinned", raw.get("isPinned", False))),
            media=media,
            raw_json=raw_json,
            content_hash=hashlib.sha256(raw_json.encode("utf-8")).hexdigest(),
        )

    def to_mapping(self) -> dict[str, Any]:
        return json.loads(self.raw_json)


@dataclass(frozen=True)
class PostDetail:
    """Normalized detail facts and the archive policy decision."""

    post: Post
    is_reply: bool = False
    is_quote: bool = False
    is_repost: bool = False

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], fallback_handle: str = "") -> "PostDetail":
        if not isinstance(value, Mapping):
            raise TypeError("post detail must be a mapping")
        post = Post.from_mapping(value, fallback_handle)
        kind = post.post_kind.lower()
        return cls(
            post=post,
            is_reply=bool(value.get("isReply", value.get("is_reply", False)))
            or kind in {"reply", "replies"}
            or bool(value.get("replyTo")),
            is_quote=bool(value.get("isQuote", value.get("is_quote", False)))
            or kind in {"quote", "quoted"}
            or bool(value.get("quotedPost")),
            is_repost=bool(value.get("isRepost", value.get("is_repost", False)))
            or kind in {"repost", "retweet", "reposted"}
            or bool(value.get("isRetweet")),
        )

    def decision_for(self, handle: str) -> str:
        target = normalize_handle(handle)
        if not target or self.post.author_handle != target:
            return "other"
        if self.post.has_video:
            return "video"
        if self.is_reply:
            return "reply"
        if self.is_quote:
            return "quote"
        if self.is_repost:
            return "repost"
        if not self.post.text and not self.post.media:
            return "other"
        return "saved"
