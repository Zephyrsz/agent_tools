"""Python client for Apple Notes backed by a small JXA bridge."""

from __future__ import annotations

import json
import platform
import subprocess
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol


DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_TITLE_CHARACTERS = 500
MAX_CONTENT_CHARACTERS = 2_000_000
VALID_CONTENT_FORMATS = {"text", "html"}


class NotesError(RuntimeError):
    """An expected Apple Notes or request error."""

    def __init__(self, message: str, *, code: str = "NOTES_ERROR") -> None:
        super().__init__(message)
        self.code = code


class Runner(Protocol):
    def run(self, action: str, params: Mapping[str, Any] | None = None) -> Any: ...


class AppleScriptRunner:
    """Execute the bundled JavaScript for Automation bridge with JSON over stdin."""

    def __init__(
        self,
        script_path: Path | None = None,
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.script_path = script_path or Path(__file__).with_name("notes_bridge.js")
        self.timeout = timeout
        self._lock = threading.Lock()

    def run(self, action: str, params: Mapping[str, Any] | None = None) -> Any:
        if platform.system() != "Darwin":
            raise NotesError(
                "Apple Notes automation is available only on macOS.",
                code="UNSUPPORTED_PLATFORM",
            )
        if not self.script_path.is_file():
            raise NotesError(
                f"Notes automation bridge was not found: {self.script_path}",
                code="BRIDGE_NOT_FOUND",
            )

        request = json.dumps(
            {"action": action, "params": dict(params or {})},
            ensure_ascii=False,
        )
        command = [
            "/usr/bin/osascript",
            "-l",
            "JavaScript",
            str(self.script_path),
        ]
        try:
            # Notes automation is serialized because simultaneous Apple events are flaky.
            with self._lock:
                completed = subprocess.run(
                    command,
                    input=request,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=self.timeout,
                )
        except subprocess.TimeoutExpired as exc:
            raise NotesError(
                f"Apple Notes did not respond within {self.timeout:g} seconds.",
                code="TIMEOUT",
            ) from exc
        except OSError as exc:
            raise NotesError(
                f"Could not start macOS automation: {exc}",
                code="AUTOMATION_START_FAILED",
            ) from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            code = "AUTOMATION_FAILED"
            lowered = detail.casefold()
            if "not authorized" in lowered or "-1743" in detail:
                code = "AUTOMATION_PERMISSION_DENIED"
                detail += (
                    " Grant the terminal or Python process access under System Settings "
                    "> Privacy & Security > Automation, then retry."
                )
            raise NotesError(detail or "Apple Notes automation failed.", code=code)

        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise NotesError(
                "Apple Notes returned an invalid automation response.",
                code="INVALID_AUTOMATION_RESPONSE",
            ) from exc

        if not isinstance(response, dict) or "ok" not in response:
            raise NotesError(
                "Apple Notes returned an unexpected automation response.",
                code="INVALID_AUTOMATION_RESPONSE",
            )
        if not response["ok"]:
            error = response.get("error") or {}
            if not isinstance(error, dict):
                raise NotesError(
                    "Apple Notes returned an unexpected automation error.",
                    code="INVALID_AUTOMATION_RESPONSE",
                )
            code = str(error.get("code") or "AUTOMATION_FAILED")
            message = str(error.get("message") or "Apple Notes automation failed.")
            if code == "AUTOMATION_PERMISSION_DENIED":
                message += (
                    " Grant the terminal or Python process access under System Settings "
                    "> Privacy & Security > Automation, then retry."
                )
            raise NotesError(
                message,
                code=code,
            )
        return response.get("result")


def _required_text(value: str, name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise NotesError(f"{name} must be a string.", code="INVALID_REQUEST")
    value = value.strip()
    if not value:
        raise NotesError(f"{name} cannot be empty.", code="INVALID_REQUEST")
    if len(value) > maximum:
        raise NotesError(
            f"{name} cannot exceed {maximum} characters.",
            code="INVALID_REQUEST",
        )
    return value


def _content(value: str) -> str:
    if not isinstance(value, str):
        raise NotesError("content must be a string.", code="INVALID_REQUEST")
    if len(value) > MAX_CONTENT_CHARACTERS:
        raise NotesError(
            f"content cannot exceed {MAX_CONTENT_CHARACTERS} characters.",
            code="INVALID_REQUEST",
        )
    return value


def _content_format(value: str) -> str:
    if value not in VALID_CONTENT_FORMATS:
        raise NotesError(
            "content_format must be either 'text' or 'html'.",
            code="INVALID_REQUEST",
        )
    return value


class NotesClient:
    """High-level Python API for accounts, folders, and notes."""

    def __init__(self, runner: Runner | None = None) -> None:
        self.runner = runner or AppleScriptRunner()

    def health(self) -> dict[str, Any]:
        return self.runner.run("health")

    def list_accounts(self) -> list[dict[str, Any]]:
        return self.runner.run("list_accounts")

    def list_folders(self, *, account: str | None = None) -> list[dict[str, Any]]:
        return self.runner.run("list_folders", {"account": account})

    def list_notes(
        self,
        *,
        account: str | None = None,
        folder: str | None = None,
        folder_id: str | None = None,
        query: str | None = None,
        recursive: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise NotesError(
                "limit must be between 1 and 1000.",
                code="INVALID_REQUEST",
            )
        if offset < 0:
            raise NotesError("offset cannot be negative.", code="INVALID_REQUEST")
        return self.runner.run(
            "list_notes",
            {
                "account": account,
                "folder": folder,
                "folder_id": folder_id,
                "query": query,
                "recursive": recursive,
                "limit": limit,
                "offset": offset,
            },
        )

    def get_note(self, note_id: str) -> dict[str, Any]:
        note_id = _required_text(note_id, "note_id", maximum=2000)
        return self.runner.run("get_note", {"note_id": note_id})

    def create_note(
        self,
        title: str,
        content: str = "",
        *,
        content_format: str = "text",
        account: str | None = None,
        folder: str | None = None,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        title = _required_text(title, "title", maximum=MAX_TITLE_CHARACTERS)
        return self.runner.run(
            "create_note",
            {
                "title": title,
                "content": _content(content),
                "content_format": _content_format(content_format),
                "account": account,
                "folder": folder,
                "folder_id": folder_id,
            },
        )

    def update_note(
        self,
        note_id: str,
        content: str,
        *,
        mode: str = "replace",
        content_format: str = "text",
        preserve_title: bool = True,
    ) -> dict[str, Any]:
        note_id = _required_text(note_id, "note_id", maximum=2000)
        if mode not in {"replace", "append"}:
            raise NotesError(
                "mode must be either 'replace' or 'append'.",
                code="INVALID_REQUEST",
            )
        return self.runner.run(
            "update_note",
            {
                "note_id": note_id,
                "content": _content(content),
                "content_format": _content_format(content_format),
                "mode": mode,
                "preserve_title": preserve_title,
            },
        )
