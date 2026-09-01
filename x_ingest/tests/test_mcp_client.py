from __future__ import annotations

import asyncio
import json
import unittest

from x_ingest.mcp_client import McpClient, McpProtocolError


class FakeTransport:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.sent: list[dict] = []

    async def request(self, message: dict, timeout: float) -> dict:
        self.sent.append(message)
        if not self.replies:
            raise AssertionError("unexpected request")
        return self.replies.pop(0)

    async def notify(self, message: dict) -> None:
        self.sent.append(message)


class McpClientTests(unittest.TestCase):
    def test_initialize_and_call_tool_decode_structured_result(self) -> None:
        async def scenario() -> None:
            transport = FakeTransport(
                [
                    {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}},
                    {"jsonrpc": "2.0", "id": 2, "result": {"structuredContent": {"ok": True}}},
                ]
            )
            client = McpClient(transport=transport)
            await client.initialize()
            result = await client.call_tool("evaluate_script", {"function": "() => 1"})
            self.assertEqual(result, {"ok": True})
            self.assertEqual(transport.sent[0]["method"], "initialize")
            self.assertEqual(transport.sent[1]["method"], "notifications/initialized")
            self.assertEqual(transport.sent[2]["method"], "tools/call")

        asyncio.run(scenario())

    def test_call_tool_surfaces_mcp_error(self) -> None:
        async def scenario() -> None:
            transport = FakeTransport(
                [{"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "bad tool"}}]
            )
            client = McpClient(transport=transport)
            with self.assertRaises(McpProtocolError):
                await client.initialize()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
