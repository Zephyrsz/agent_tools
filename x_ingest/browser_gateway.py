"""Chrome DevTools MCP browser gateway used by the crawl coordinator."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import AppConfig
from .mcp_client import McpClient, StdioTransport
from .models import normalize_handle


class BrowserGatewayError(RuntimeError):
    pass


class BrowserAuthenticationError(BrowserGatewayError):
    pass


LOGIN_PROBE = r"""(() => {
  const path = (location.pathname || "").toLowerCase();
  const text = (document.body?.innerText || "").toLowerCase();
  const hostOk = /^(x\.com|www\.x\.com|twitter\.com|www\.twitter\.com)$/.test(location.hostname);
  const loginRoute = path === "/" || /\/(?:i\/flow\/login|login|signup|account\/access|challenge|welcome)(?:\/|$)/.test(path);
  const loginCopy = /log in to x|sign in|create account|login|登录|使用 google 继续|注册/.test(text);
  const homeRoute = path === "/home" || path.startsWith("/home/");
  return { authenticated: hostOk && homeRoute && !loginRoute && !loginCopy, url: location.href };
})"""


def _find_page_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("pageId", "page_id", "targetId", "target_id", "id"):
            candidate = value.get(key)
            if isinstance(candidate, (str, int)) and str(candidate).strip():
                return str(candidate)
        for item in value.values():
            found = _find_page_id(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_page_id(item)
            if found:
                return found
    return None


class ChromeDevToolsMcpGateway:
    """Deep browser seam: navigation and page-context extraction over MCP."""

    def __init__(self, config: AppConfig, *, client: McpClient | Any | None = None) -> None:
        self.config = config
        self.client = client
        self._transport: StdioTransport | None = None
        self._started = False
        self._page_id: str | None = None
        self._extractor_root = Path(__file__).resolve().parent / "extractors"

    async def start(self) -> None:
        if self._started:
            return
        if self.client is None:
            command = list(self.config.browser.mcp_command)
            if not any("browserUrl" in item or "browser-url" in item for item in command):
                command.append(f"--browserUrl={self.config.browser.cdp_url}")
            self._transport = StdioTransport(tuple(command))
            await self._transport.start()
            self.client = McpClient(transport=self._transport, timeout=self.config.browser.mcp_timeout)
        await self.client.initialize()
        result = await self.client.call_tool(self.config.browser.new_page_tool, {"url": "about:blank"})
        self._page_id = _find_page_id(result)
        self._started = True

    async def close(self) -> None:
        if self.client is None:
            return
        try:
            if self._page_id:
                try:
                    await self.client.call_tool(
                        self.config.browser.close_page_tool, {"pageId": self._page_id}
                    )
                except Exception:
                    pass
            await self.client.close()
        finally:
            self.client = None
            self._transport = None
            self._page_id = None
            self._started = False

    async def _call(self, tool: str, arguments: dict[str, Any]) -> Any:
        if not self._started:
            await self.start()
        if self._page_id:
            arguments = {**arguments, "pageId": self._page_id}
        return await self.client.call_tool(tool, arguments)

    async def navigate(self, url: str) -> dict[str, Any]:
        parsed = urlparse(str(url))
        if parsed.hostname not in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
            raise BrowserGatewayError("navigation target is outside allowed X domains")
        result = await self._call(self.config.browser.navigate_tool, {"url": str(url)})
        return result if isinstance(result, dict) else {"result": result}

    def _load_script(self, name: str) -> str:
        try:
            return (self._extractor_root / name).read_text(encoding="utf-8")
        except OSError as exc:
            raise BrowserGatewayError(f"extractor script unavailable: {name}") from exc

    async def evaluate(self, script: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        options_json = json.dumps(options or {}, ensure_ascii=False, separators=(",", ":"))
        function = f"async () => {{ const fn = {script.strip()}; return await fn({options_json}); }}"
        result = await self._call(self.config.browser.evaluate_tool, {"function": function})
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except json.JSONDecodeError as exc:
                raise BrowserGatewayError("MCP evaluator returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise BrowserGatewayError("MCP evaluator returned a non-object")
        if result.get("error") and not result.get("skipped"):
            error = result["error"]
            message = error.get("message", "page extractor failed") if isinstance(error, dict) else str(error)
            raise BrowserGatewayError(str(message)[:300])
        return result

    async def open_timeline(self, handle: str) -> None:
        normalized = normalize_handle(handle)
        if not normalized:
            raise ValueError("timeline handle is required")
        await self.navigate(f"https://x.com/{normalized}")

    async def discover_candidates(self, handle: str, **options: Any) -> dict[str, Any]:
        if not options.pop("continueTimeline", False):
            await self.open_timeline(handle)
        values = {
            "handle": normalize_handle(handle),
            "maxScrolls": self.config.browser.max_scrolls,
            "waitMs": self.config.browser.wait_ms,
            "limit": self.config.browser.batch_size,
            **options,
        }
        result = await self.evaluate(self._load_script("timeline.js"), values)
        if "candidates" not in result and isinstance(result.get("posts"), list):
            result["candidates"] = result["posts"]
        if "status" not in result:
            result["status"] = "complete" if result.get("exhausted") else "partial"
        result.setdefault("handle", normalize_handle(handle))
        result.setdefault("candidates", [])
        return result

    async def extract_detail(self, url: str) -> dict[str, Any]:
        await self.navigate(url)
        result = await self.evaluate(self._load_script("post_detail.js"), {})
        result.setdefault("url", str(url))
        parts = urlparse(str(url)).path.rstrip("/").split("/")
        if "status" in parts:
            index = parts.index("status")
            if index > 0:
                result.setdefault("handle", normalize_handle(parts[index - 1]))
            if index + 1 < len(parts):
                result.setdefault("postId", parts[index + 1])
        return result

    async def is_authenticated(self) -> bool:
        try:
            await self.navigate("https://x.com/home")
            return bool((await self.evaluate(LOGIN_PROBE, {})).get("authenticated"))
        except Exception:
            return False

    async def login(self, *, timeout: float = 300.0, poll_interval: float = 1.2) -> dict[str, Any]:
        await self.start()
        await self.navigate("https://x.com/home")
        import asyncio
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.0, float(timeout))
        while True:
            result = await self.evaluate(LOGIN_PROBE, {})
            if result.get("authenticated") or loop.time() >= deadline:
                return result
            await asyncio.sleep(max(0.1, float(poll_interval)))
