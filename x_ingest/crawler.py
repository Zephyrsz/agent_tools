"""Resumable candidate/detail crawl coordinator."""

from __future__ import annotations

from typing import Any

from .models import PostDetail, normalize_handle


class CrawlError(RuntimeError):
    pass


class CrawlCoordinator:
    """Orchestrates browser extraction while keeping persistence transactional.

    The browser gateway only returns rendered facts. This module owns policy:
    every candidate gets a detail-page visit and only an author's original,
    non-video post is passed to the repository.
    """

    def __init__(self, repository: Any, gateway: Any) -> None:
        self.repository = repository
        self.gateway = gateway

    async def crawl(
        self,
        handle: str,
        *,
        mode: str = "incremental",
        limit: int | None = None,
        requested_from: str | None = None,
        requested_until: str | None = None,
        discovery_options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = normalize_handle(handle)
        if not target:
            raise ValueError("crawl handle is required")

        await self.gateway.start()
        run_id = self.repository.begin_crawl(
            target,
            mode=mode,
            requested_from=requested_from,
            requested_until=requested_until,
        )
        counts = {
            "run_id": run_id,
            "fetched": 0,
            "saved": 0,
            "inserted": 0,
            "updated": 0,
            "unchanged": 0,
            "skipped": 0,
            "errors": 0,
            "successful": False,
        }
        stop_reason = ""
        discovery_status = "partial"
        try:
            if not await self.gateway.is_authenticated():
                raise CrawlError("Chrome profile is not authenticated to X")
            options = dict(discovery_options or {})
            if limit is not None:
                options["limit"] = max(1, int(limit))
            options.setdefault("markComplete", mode != "backfill")
            if mode == "incremental" and "stopAtTimestamp" not in options:
                state = getattr(self.repository, "get_state", lambda _handle: None)(target)
                if state and state.get("newest_seen_at"):
                    options["stopAtTimestamp"] = state["newest_seen_at"]
                    options["stopAtId"] = state.get("newest_seen_id", "")
            discovered = await self.gateway.discover_candidates(target, **options)
            discovery_status = str(discovered.get("status", "partial")).lower()
            stop_reason = str(discovered.get("stopReason", ""))
            candidates = discovered.get("candidates")
            if not isinstance(candidates, list):
                # Keep compatibility with the extractor's historical `posts`
                # key while the durable queue uses the clearer candidate name.
                candidates = discovered.get("posts", [])
            for value in candidates:
                url = value if isinstance(value, str) else value.get("url", "") if isinstance(value, dict) else ""
                if not str(url).strip():
                    counts["skipped"] += 1
                    continue
                counts["fetched"] += 1
                candidate_id = self._add_candidate(run_id, target, str(url), value)
                try:
                    detail_value = await self.gateway.extract_detail(str(url))
                    if not isinstance(detail_value, dict):
                        raise CrawlError("detail extractor returned a non-object")
                    if detail_value.get("skipped"):
                        decision = self._skip_decision(detail_value)
                        counts["skipped"] += 1
                        self._update_candidate(candidate_id, decision, detail_value)
                        continue
                    detail = PostDetail.from_mapping(detail_value, target)
                    decision = detail.decision_for(target)
                    if decision == "saved":
                        stored = self.repository.upsert_posts(
                            [detail.post],
                            handle=target,
                            captured_at=detail.post.created_at,
                            relation="own_post",
                        )
                        for key in ("inserted", "updated", "unchanged"):
                            counts[key] += int(stored.get(key, 0))
                        counts["saved"] += 1
                    else:
                        counts["skipped"] += 1
                    self._update_candidate(candidate_id, decision, detail_value)
                except Exception as exc:
                    counts["errors"] += 1
                    self._update_candidate(candidate_id, "error", {"error": str(exc)[:500]})
            counts["successful"] = discovery_status == "complete" and counts["errors"] == 0
            if not counts["successful"] and not stop_reason:
                stop_reason = "detail extraction failed" if counts["errors"] else "timeline boundary is partial"
        except Exception as exc:
            counts["errors"] += 1
            stop_reason = str(exc)[:500]
        finally:
            self.repository.finish_crawl(
                run_id,
                fetched_count=counts["fetched"],
                inserted_count=counts["inserted"],
                updated_count=counts["updated"],
                unchanged_count=counts["unchanged"],
                skipped_count=counts["skipped"],
                error_count=counts["errors"],
                stop_reason=stop_reason,
                successful=counts["successful"],
            )
            await self.gateway.close()
        return counts

    def _add_candidate(self, run_id: int, handle: str, url: str, value: Any) -> int | None:
        method = getattr(self.repository, "add_candidate", None)
        if method is None:
            enqueue = getattr(self.repository, "enqueue_candidate", None)
            if enqueue is None:
                return None
            from .models import post_id_from_url
            post_id = post_id_from_url(url)
            if not post_id:
                return None
            enqueue(handle, post_id, url, raw_json=str(value) if isinstance(value, dict) else None)
            return (handle, post_id)  # type: ignore[return-value]
        metadata = dict(value) if isinstance(value, dict) else {}
        metadata.pop("url", None)
        return method(run_id, handle, url, **metadata)

    def _update_candidate(self, candidate_id: int | None, status: str, metadata: dict[str, Any]) -> None:
        if candidate_id is None:
            return
        method = getattr(self.repository, "update_candidate", None)
        if method is not None:
            method(candidate_id, status, **metadata)
            return
        mark = getattr(self.repository, "mark_candidate", None)
        if mark is not None and isinstance(candidate_id, tuple):
            handle, post_id = candidate_id
            error = metadata.get("error")
            mark(handle, post_id, status=status, error=error)

    @staticmethod
    def _skip_decision(value: dict[str, Any]) -> str:
        reason = str(value.get("skipReason", "other")).lower()
        if "video" in reason:
            return "video"
        return "other"
