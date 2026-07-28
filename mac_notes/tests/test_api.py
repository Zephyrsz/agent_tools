from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from mac_notes.api import create_app
from mac_notes.client import NotesError


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def health(self) -> dict[str, Any]:
        return {"ok": True, "account_count": 1}

    def list_accounts(self) -> list[dict[str, Any]]:
        return [{"id": "account-1", "name": "iCloud"}]

    def list_folders(self, **params: Any) -> list[dict[str, Any]]:
        self.calls.append(("list_folders", params))
        return []

    def list_notes(self, **params: Any) -> list[dict[str, Any]]:
        self.calls.append(("list_notes", params))
        return [{"id": "note-1", "name": "Roadmap"}]

    def get_note(self, note_id: str) -> dict[str, Any]:
        self.calls.append(("get_note", {"note_id": note_id}))
        if note_id == "missing":
            raise NotesError("not found", code="NOTE_NOT_FOUND")
        return {"id": note_id, "plaintext": "hello"}

    def create_note(self, **params: Any) -> dict[str, Any]:
        self.calls.append(("create_note", params))
        return {"id": "created", **params}

    def update_note(self, note_id: str, **params: Any) -> dict[str, Any]:
        self.calls.append(("update_note", {"note_id": note_id, **params}))
        return {"id": note_id, **params}


def test_list_and_read_routes() -> None:
    fake = FakeClient()
    client = TestClient(create_app(fake))

    listing = client.get(
        "/api/notes",
        params={"folder": "Work", "recursive": "true", "limit": 20},
    )
    note = client.get("/api/notes/x-coredata://abc/Note/p1")

    assert listing.status_code == 200
    assert listing.json()[0]["name"] == "Roadmap"
    assert fake.calls[0] == (
        "list_notes",
        {
            "account": None,
            "folder": "Work",
            "folder_id": None,
            "query": None,
            "recursive": True,
            "limit": 20,
            "offset": 0,
        },
    )
    assert note.status_code == 200
    assert note.json()["id"] == "x-coredata://abc/Note/p1"


def test_create_and_append_routes() -> None:
    fake = FakeClient()
    client = TestClient(create_app(fake))

    created = client.post(
        "/api/notes",
        json={"title": "记录", "content": "第一行", "folder": "工作"},
    )
    updated = client.put(
        "/api/notes/note-1",
        json={"content": "第二行", "mode": "append"},
    )

    assert created.status_code == 201
    assert created.json()["id"] == "created"
    assert updated.status_code == 200
    assert updated.json()["mode"] == "append"


def test_error_is_structured_and_mapped_to_404() -> None:
    response = TestClient(create_app(FakeClient())).get("/api/notes/missing")

    assert response.status_code == 404
    assert response.json() == {
        "detail": {"code": "NOTE_NOT_FOUND", "message": "not found"}
    }


def test_non_local_host_and_origin_are_rejected() -> None:
    client = TestClient(create_app(FakeClient()))

    remote_host = client.get("/api/health", headers={"host": "192.168.1.50"})
    remote_origin = client.get(
        "/api/health",
        headers={"origin": "https://untrusted.example"},
    )

    assert remote_host.status_code == 403
    assert remote_origin.status_code == 403


def test_request_validation_rejects_extra_fields() -> None:
    response = TestClient(create_app(FakeClient())).post(
        "/api/notes",
        json={"title": "Example", "content": "text", "unexpected": True},
    )

    assert response.status_code == 422
