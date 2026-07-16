from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .core import MANAGED_COOKIES_PATH, MAX_COOKIE_FILE_BYTES, Settings, dependency_status, store_managed_cookies
from .downloader import DownloadError, DownloadManager, VideoService


BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
video_service = VideoService()
download_manager = DownloadManager()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await download_manager.start()
    yield
    await download_manager.stop()


app = FastAPI(title="TubeSafe", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.middleware("http")
async def localhost_only(request: Request, call_next):
    host = request.url.hostname
    if host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
        return JSONResponse({"detail": "TubeSafe 仅接受本机访问"}, status_code=403)
    origin = request.headers.get("origin")
    if origin:
        origin_host = urlparse(origin).hostname
        if origin_host not in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return JSONResponse({"detail": "拒绝跨站请求"}, status_code=403)
    return await call_next(request)


class ParseRequest(BaseModel):
    url: str = Field(min_length=6, max_length=500)


class TaskRequest(BaseModel):
    url: str = Field(min_length=6, max_length=500)
    title: str = Field(min_length=1, max_length=240)
    format_id: str = Field(min_length=1, max_length=160)
    format_label: str = Field(min_length=1, max_length=40)


class SettingsRequest(BaseModel):
    download_dir: str = Field(min_length=1, max_length=1000)
    connections: int = Field(ge=1, le=4)
    sleep_min: int = Field(ge=0, le=30)
    sleep_max: int = Field(ge=0, le=60)
    proxy_url: str | None = Field(default=None, max_length=1000)
    cookies_path: str = Field(default="", max_length=1000)
    cookies_browser: str = Field(default="", max_length=20)


def api_error(exc: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


@app.get("/api/health")
async def health() -> dict[str, Any]:
    dependencies = dependency_status()
    return {
        "ok": all(item["ok"] for item in dependencies.values()),
        "dependencies": dependencies,
        "profile": "conservative",
        "queue_concurrency": 1,
    }


@app.get("/api/settings")
async def get_settings() -> dict[str, object]:
    return Settings.load().public()


@app.put("/api/settings")
async def update_settings(payload: SettingsRequest) -> dict[str, object]:
    try:
        data = payload.model_dump()
        current = Settings.load()
        if data["proxy_url"] is None:
            data["proxy_url"] = current.proxy_url
        settings = Settings(**data).validated()
        settings.save()
        return settings.public()
    except (ValueError, OSError) as exc:
        raise api_error(exc) from exc


@app.post("/api/cookies/upload")
async def upload_cookies(file: UploadFile = File(...)) -> dict[str, object]:
    try:
        data = await file.read(MAX_COOKIE_FILE_BYTES + 1)
        path = store_managed_cookies(data)
        settings = Settings.load()
        settings.cookies_browser = ""
        settings.cookies_path = str(path)
        settings.save()
        result = settings.public()
        result["uploaded_name"] = Path(file.filename or "cookies.txt").name
        return result
    except (ValueError, OSError) as exc:
        raise api_error(exc) from exc
    finally:
        await file.close()


@app.delete("/api/cookies", status_code=204)
async def clear_cookies() -> None:
    settings = Settings.load()
    settings.cookies_browser = ""
    settings.cookies_path = ""
    settings.save()
    MANAGED_COOKIES_PATH.unlink(missing_ok=True)


@app.post("/api/parse")
async def parse_video(payload: ParseRequest) -> dict[str, Any]:
    missing = [item["label"] for item in dependency_status().values() if not item["ok"]]
    if missing:
        raise api_error(RuntimeError(f"缺少依赖：{', '.join(missing)}"), 503)
    try:
        return await video_service.parse(payload.url, Settings.load())
    except (ValueError, DownloadError) as exc:
        raise api_error(exc) from exc


@app.get("/api/tasks")
async def list_tasks() -> list[dict[str, Any]]:
    return [task.public() for task in reversed(download_manager.tasks.values())]


@app.post("/api/tasks", status_code=201)
async def create_task(payload: TaskRequest) -> dict[str, Any]:
    try:
        return download_manager.add(**payload.model_dump()).public()
    except (ValueError, DownloadError) as exc:
        raise api_error(exc) from exc


@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict[str, Any]:
    try:
        return (await download_manager.cancel(task_id)).public()
    except DownloadError as exc:
        raise api_error(exc, 404) from exc


@app.delete("/api/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str) -> None:
    try:
        download_manager.remove(task_id)
    except DownloadError as exc:
        raise api_error(exc, 409) from exc


@app.get("/api/files/{task_id}")
async def get_file(task_id: str):
    try:
        task = download_manager.get(task_id)
    except DownloadError as exc:
        raise api_error(exc, 404) from exc
    if task.status != "completed" or not task.file_path:
        raise api_error(RuntimeError("文件尚未就绪"), 409)
    path = Path(task.file_path)
    if not path.is_file():
        raise api_error(RuntimeError("本地文件已被移动或删除"), 404)
    return FileResponse(path, filename=path.name)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
