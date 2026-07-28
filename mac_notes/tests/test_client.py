from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from typing import Any

import pytest

from mac_notes.client import AppleScriptRunner, NotesClient, NotesError


class FakeRunner:
    def __init__(self, result: Any = None) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def run(self, action: str, params: Mapping[str, Any] | None = None) -> Any:
        self.calls.append((action, dict(params or {})))
        return self.result


def test_list_notes_forwards_filters() -> None:
    runner = FakeRunner([{"id": "note-1", "name": "Example"}])
    client = NotesClient(runner)

    result = client.list_notes(
        account="iCloud",
        folder="Work/Plans",
        query="roadmap",
        recursive=True,
        limit=20,
        offset=5,
    )

    assert result == [{"id": "note-1", "name": "Example"}]
    assert runner.calls == [
        (
            "list_notes",
            {
                "account": "iCloud",
                "folder": "Work/Plans",
                "folder_id": None,
                "query": "roadmap",
                "recursive": True,
                "limit": 20,
                "offset": 5,
            },
        )
    ]


@pytest.mark.parametrize(
    ("limit", "offset"),
    [(0, 0), (1001, 0), (10, -1)],
)
def test_list_notes_rejects_bad_pagination(limit: int, offset: int) -> None:
    with pytest.raises(NotesError) as captured:
        NotesClient(FakeRunner()).list_notes(limit=limit, offset=offset)

    assert captured.value.code == "INVALID_REQUEST"


def test_create_note_preserves_unicode_content() -> None:
    runner = FakeRunner({"id": "new-id"})
    result = NotesClient(runner).create_note(
        "项目记录",
        "第一行\n第二行",
        folder="工作",
    )

    assert result == {"id": "new-id"}
    assert runner.calls[0] == (
        "create_note",
        {
            "title": "项目记录",
            "content": "第一行\n第二行",
            "content_format": "text",
            "account": None,
            "folder": "工作",
            "folder_id": None,
        },
    )


def test_update_note_rejects_unknown_mode_without_calling_runner() -> None:
    runner = FakeRunner()
    with pytest.raises(NotesError) as captured:
        NotesClient(runner).update_note("note-1", "text", mode="merge")

    assert captured.value.code == "INVALID_REQUEST"
    assert runner.calls == []


def test_note_id_is_trimmed() -> None:
    runner = FakeRunner({"id": "note-1"})
    NotesClient(runner).get_note("  note-1  ")

    assert runner.calls == [("get_note", {"note_id": "note-1"})]


def test_automation_runner_uses_json_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["options"] = options
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='{"ok":true,"result":{"id":"note-1"}}',
            stderr="",
        )

    monkeypatch.setattr("mac_notes.client.platform.system", lambda: "Darwin")
    monkeypatch.setattr("mac_notes.client.subprocess.run", fake_run)

    result = AppleScriptRunner().run(
        "create_note",
        {"title": "中文", "content": "a\nb"},
    )

    request = json.loads(captured["options"]["input"])
    assert captured["command"][:3] == ["/usr/bin/osascript", "-l", "JavaScript"]
    assert request == {
        "action": "create_note",
        "params": {"title": "中文", "content": "a\nb"},
    }
    assert result == {"id": "note-1"}


def test_automation_permission_error_has_actionable_help(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(
                '{"ok":false,"error":'
                '{"code":"AUTOMATION_PERMISSION_DENIED","message":"Not authorized"}}'
            ),
            stderr="",
        )

    monkeypatch.setattr("mac_notes.client.platform.system", lambda: "Darwin")
    monkeypatch.setattr("mac_notes.client.subprocess.run", fake_run)

    with pytest.raises(NotesError) as captured:
        AppleScriptRunner().run("health")

    assert captured.value.code == "AUTOMATION_PERMISSION_DENIED"
    assert "Privacy & Security > Automation" in str(captured.value)
