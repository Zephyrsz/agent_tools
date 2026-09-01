from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from x_ingest.browser_gateway import ChromeDevToolsMcpGateway
from x_ingest.config import AppConfig, BrowserConfig


class FakeMcp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def initialize(self) -> dict:
        return {}

    async def call_tool(self, name: str, arguments: dict) -> object:
        self.calls.append((name, arguments))
        if name == "new_page":
            return {"pageId": "page-1"}
        if name == "navigate_page":
            return {"url": arguments["url"]}
        if name == "evaluate_script":
            if "authenticated" in arguments["function"]:
                return {"authenticated": True, "url": "https://x.com/home"}
            if "candidates" in arguments["function"] or "extractVisiblePosts" in arguments["function"]:
                return {"candidates": [], "status": "complete", "exhausted": True}
            return {"postId": "123", "text": "hello"}
        return {}

    async def close(self) -> None:
        pass


class BrowserGatewayTests(unittest.TestCase):
    def test_gateway_creates_page_and_decodes_extractors(self) -> None:
        async def scenario() -> None:
            mcp = FakeMcp()
            config = AppConfig(browser=BrowserConfig(mcp_command=("node", "fake")))
            gateway = ChromeDevToolsMcpGateway(config, client=mcp)
            await gateway.start()
            self.assertTrue(await gateway.is_authenticated())
            await gateway.open_timeline("@Example")
            batch = await gateway.discover_candidates("Example")
            detail = await gateway.extract_detail("https://x.com/example/status/123")
            self.assertEqual(batch["status"], "complete")
            self.assertEqual(detail["postId"], "123")
            self.assertEqual([name for name, _ in mcp.calls[:3]], ["new_page", "navigate_page", "evaluate_script"])
            await gateway.close()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
