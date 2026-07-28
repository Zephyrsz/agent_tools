"""Local-only FastAPI application for Apple Notes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .client import (
    MAX_CONTENT_CHARACTERS,
    MAX_TITLE_CHARACTERS,
    NotesClient,
    NotesError,
)


LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}
NOT_FOUND_CODES = {"ACCOUNT_NOT_FOUND", "FOLDER_NOT_FOUND", "NOTE_NOT_FOUND"}


class CreateNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARACTERS)
    content: str = Field(default="", max_length=MAX_CONTENT_CHARACTERS)
    content_format: Literal["text", "html"] = "text"
    account: str | None = None
    folder: str | None = None
    folder_id: str | None = None


class UpdateNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=MAX_CONTENT_CHARACTERS)
    content_format: Literal["text", "html"] = "text"
    mode: Literal["replace", "append"] = "replace"
    preserve_title: bool = True


def error_status(error: NotesError) -> int:
    if error.code in NOT_FOUND_CODES:
        return 404
    if error.code == "AMBIGUOUS_FOLDER":
        return 409
    if error.code == "INVALID_REQUEST":
        return 422
    if error.code == "AUTOMATION_PERMISSION_DENIED":
        return 403
    if error.code == "UNSUPPORTED_PLATFORM":
        return 501
    if error.code == "TIMEOUT":
        return 504
    return 503


def create_app(client: NotesClient | None = None) -> FastAPI:
    notes = client or NotesClient()
    app = FastAPI(
        title="macOS Notes API",
        version="0.1.0",
        description="A localhost-only API for the current user's Apple Notes.",
    )

    @app.middleware("http")
    async def localhost_only(request: Request, call_next: Callable[..., Any]):
        host = request.url.hostname
        if host not in LOCAL_HOSTS:
            return JSONResponse(
                {
                    "detail": {
                        "code": "LOCALHOST_ONLY",
                        "message": "Only local requests are allowed.",
                    }
                },
                status_code=403,
            )
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in LOCAL_HOSTS:
            return JSONResponse(
                {
                    "detail": {
                        "code": "CROSS_SITE_REQUEST",
                        "message": "Cross-site requests are not allowed.",
                    }
                },
                status_code=403,
            )
        return await call_next(request)

    @app.exception_handler(NotesError)
    async def notes_error_handler(_: Request, error: NotesError) -> JSONResponse:
        return JSONResponse(
            {"detail": {"code": error.code, "message": str(error)}},
            status_code=error_status(error),
        )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return notes.health()

    @app.get("/api/accounts")
    def list_accounts() -> list[dict[str, Any]]:
        return notes.list_accounts()

    @app.get("/api/folders")
    def list_folders(account: str | None = None) -> list[dict[str, Any]]:
        return notes.list_folders(account=account)

    @app.get("/api/notes")
    def list_notes(
        account: str | None = None,
        folder: str | None = None,
        folder_id: str | None = None,
        query: str | None = None,
        recursive: bool = False,
        limit: int = Query(default=100, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> list[dict[str, Any]]:
        return notes.list_notes(
            account=account,
            folder=folder,
            folder_id=folder_id,
            query=query,
            recursive=recursive,
            limit=limit,
            offset=offset,
        )

    @app.post("/api/notes", status_code=201)
    def create_note(payload: CreateNoteRequest) -> dict[str, Any]:
        return notes.create_note(**payload.model_dump())

    @app.get("/api/notes/{note_id:path}")
    def get_note(note_id: str) -> dict[str, Any]:
        return notes.get_note(note_id)

    @app.put("/api/notes/{note_id:path}")
    def update_note(note_id: str, payload: UpdateNoteRequest) -> dict[str, Any]:
        return notes.update_note(note_id, **payload.model_dump())

    return app


app = create_app()
