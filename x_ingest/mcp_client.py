"""Minimal Model Context Protocol client for a stdio tool server."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol


class McpError(RuntimeError):
    pass


class McpProtocolError(McpError):
    pass


class McpTransport(Protocol):
    async def request(self, message: dict[str, Any], timeout: float) -> dict[str, Any]: ...
    async def notify(self, message: dict[str, Any]) -> None: ...


class StdioTransport:
    """Newline-delimited JSON-RPC transport for an MCP child process."""

    def __init__(self, command: tuple[str, ...]) -> None:
        self.command = tuple(command)
        self.process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self.process is not None:
            return
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    async def close(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
            try:
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    async def notify(self, message: dict[str, Any]) -> None:
        await self._write(message)

    async def _write(self, message: dict[str, Any]) -> None:
        await self.start()
        assert self.process is not None
        if self.process.stdin is None:
            raise McpProtocolError("MCP server stdin is unavailable")
        data = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        self.process.stdin.write(data)
        await self.process.stdin.drain()

    async def request(self, message: dict[str, Any], timeout: float) -> dict[str, Any]:
        async with self._lock:
            await self._write(message)
            assert self.process is not None
            if self.process.stdout is None:
                raise McpProtocolError("MCP server stdout is unavailable")
            while True:
                try:
                    line = await asyncio.wait_for(self.process.stdout.readline(), timeout)
                except asyncio.TimeoutError as exc:
                    raise McpProtocolError("MCP request timed out") from exc
                if not line:
                    stderr = b""
                    if self.process.stderr is not None:
                        try:
                            stderr = await asyncio.wait_for(self.process.stderr.read(2048), 0.1)
                        except asyncio.TimeoutError:
                            pass
                    detail = stderr.decode("utf-8", "replace").strip()
                    raise McpProtocolError(f"MCP server exited{': ' + detail if detail else ''}")
                try:
                    response = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(response, dict) and response.get("id") == message.get("id"):
                    return response


class McpClient:
    def __init__(self, *, transport: McpTransport, timeout: float = 30.0) -> None:
        self.transport = transport
        self.timeout = float(timeout)
        self._request_id = 0
        self.initialized = False

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id()
        response = await self.transport.request(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
            self.timeout,
        )
        if response.get("id") != request_id:
            raise McpProtocolError("MCP response ID did not match request")
        if "error" in response:
            error = response.get("error")
            message = error.get("message", "MCP error") if isinstance(error, dict) else str(error)
            raise McpProtocolError(str(message))
        result = response.get("result")
        if not isinstance(result, dict):
            raise McpProtocolError("MCP response result must be an object")
        return result

    async def initialize(self) -> dict[str, Any]:
        if self.initialized:
            return {}
        result = await self._request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "x_ingest", "version": "1.0"},
            },
        )
        await self.transport.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.initialized = True
        return result

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if not self.initialized:
            await self.initialize()
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise McpProtocolError(self._content_text(result) or f"MCP tool failed: {name}")
        if "structuredContent" in result:
            return result["structuredContent"]
        text = self._content_text(result)
        if not text:
            return result
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    @staticmethod
    def _content_text(result: dict[str, Any]) -> str:
        content = result.get("content")
        if not isinstance(content, list):
            return ""
        return "\n".join(
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ).strip()

    async def close(self) -> None:
        close = getattr(self.transport, "close", None)
        if close is not None:
            await close()
