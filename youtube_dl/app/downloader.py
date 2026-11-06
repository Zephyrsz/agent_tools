from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .core import Settings, normalize_youtube_url


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
PROGRESS_RE = re.compile(r"PROGRESS:(?P<percent>[\d.]+)%\|(?P<speed>[^|]*)\|(?P<eta>.*)")
TASK_LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "tasks"
logger = logging.getLogger(__name__)


class DownloadError(RuntimeError):
    pass


def task_log_path(task_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", task_id):
        raise DownloadError("无效的任务编号")
    return TASK_LOG_DIR / f"{task_id}.log"


def _redact_output(text: str) -> str:
    text = ANSI_RE.sub("", text)
    text = re.sub(r"(?:https?|socks[45]h?)://[^\s]+", "[URL 已隐藏]", text, flags=re.I)
    return re.sub(r"((?:proxy-)?authorization|(?:set-)?cookie)(\s*:\s*)[^\r\n]*", r"\1\2[已隐藏]", text, flags=re.I)


def _task_log(task: Task, message: str) -> None:
    TASK_LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = task_log_path(task.id)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
        handle.write(f"[{timestamp}] {_redact_output(message)}\n")


@dataclass(slots=True)
class Task:
    id: str
    url: str
    title: str
    format_id: str
    format_label: str
    status: str = "queued"
    progress: float = 0
    speed: str = ""
    eta: str = ""
    detail: str = "等待下载"
    file_path: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def public(self) -> dict[str, Any]:
        data = asdict(self)
        data["ready"] = self.status == "completed" and bool(self.file_path)
        data["log_available"] = task_log_path(self.id).is_file()
        data.pop("file_path", None)
        data.pop("url", None)
        return data


def _common_args(settings: Settings) -> list[str]:
    args = [
        "yt-dlp",
        "--ignore-config",
        "--no-playlist",
        "--js-runtimes",
        "node",
        "--remote-components",
        "ejs:github",
        "--socket-timeout",
        "20",
        "--retries",
        "8",
        "--fragment-retries",
        "8",
        "--extractor-retries",
        "5",
        "--sleep-requests",
        "1",
        "--sleep-interval",
        str(settings.sleep_min),
        "--max-sleep-interval",
        str(settings.sleep_max),
    ]
    if settings.proxy_url:
        args.extend(["--proxy", settings.proxy_url])
    if settings.cookies_browser:
        args.extend(["--cookies-from-browser", settings.cookies_browser])
    elif settings.cookies_path:
        if not Path(settings.cookies_path).is_file():
            raise DownloadError("Cookie 文件不存在，请在设置中更新路径")
        args.extend(["--cookies", settings.cookies_path])
    return args


async def _run_json(args: list[str], timeout: int = 90) -> dict[str, Any]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise DownloadError("解析超时，请稍后重试或配置 Cookie/代理") from None
    if process.returncode:
        message = stderr.decode("utf-8", "replace").strip().splitlines()
        detail = message[-1] if message else "yt-dlp 解析失败"
        raise DownloadError(_friendly_error(detail))
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise DownloadError("解析器返回了无效数据，请更新 yt-dlp") from exc


def _friendly_error(detail: str) -> str:
    clean = _redact_output(detail).removeprefix("ERROR: ").strip()
    lower = clean.lower()
    if "sign in" in lower or "confirm you’re not a bot" in lower or "not a bot" in lower:
        return "YouTube 要求验证身份，请选择已登录 YouTube 的浏览器作为 Cookie 来源"
    if "could not find" in lower and "cookie" in lower:
        return "没有找到所选浏览器的 Cookie，请确认该浏览器已安装并登录 YouTube"
    if "failed to decrypt" in lower or "unable to decrypt" in lower:
        return "无法解密浏览器 Cookie，请允许系统钥匙串访问，或改用导出的 Cookie 文件"
    if "database is locked" in lower or "cookie database" in lower and "locked" in lower:
        return "浏览器 Cookie 数据库正在使用中，请完全退出该浏览器后重试"
    if "429" in lower or "too many requests" in lower:
        return "请求过于频繁（429），队列已停止；请等待一段时间或更换合规网络出口"
    if "403" in lower:
        return "媒体地址被拒绝（403），请重新解析并检查 Cookie/代理出口是否一致"
    if "requested format is not available" in lower:
        return "所选格式已失效，请重新解析视频格式"
    return clean[-360:] if clean else "操作失败，请查看终端日志"


def _format_options(info: dict[str, Any]) -> list[dict[str, Any]]:
    by_height: dict[int, dict[str, Any]] = {}
    has_audio = False
    for item in info.get("formats") or []:
        if item.get("acodec") not in {None, "none"}:
            has_audio = True
        height = item.get("height")
        if not isinstance(height, int) or item.get("vcodec") in {None, "none"}:
            continue
        ext = item.get("ext") or ""
        current = by_height.get(height)
        score = (ext == "mp4", item.get("acodec") not in {None, "none"}, item.get("tbr") or 0)
        if current is None or score > current["_score"]:
            combined = item.get("acodec") not in {None, "none"}
            selector = str(item["format_id"]) if combined else f"{item['format_id']}+bestaudio[ext=m4a]/{item['format_id']}+bestaudio"
            by_height[height] = {
                "id": selector,
                "label": f"{height}p",
                "container": "MP4" if ext == "mp4" else ext.upper(),
                "fps": item.get("fps"),
                "size": item.get("filesize") or item.get("filesize_approx"),
                "needs_merge": not combined,
                "_score": score,
            }

    options = [by_height[key] for key in sorted(by_height, reverse=True)]
    for option in options:
        option.pop("_score", None)
    options = options[:8]
    if has_audio:
        options.append({
            "id": "bestaudio[ext=m4a]/bestaudio",
            "label": "仅音频",
            "container": "M4A",
            "fps": None,
            "size": None,
            "needs_merge": False,
        })
    return options


class VideoService:
    def __init__(self) -> None:
        self._cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()

    async def parse(self, raw_url: str, settings: Settings) -> dict[str, Any]:
        url = normalize_youtube_url(raw_url)
        cached = self._cache.get(url)
        if cached and time.time() - cached[0] < 600:
            return cached[1]
        args = _common_args(settings) + [
            "--ignore-no-formats-error",
            "--dump-single-json",
            "--skip-download",
            url,
        ]
        info = await _run_json(args)
        formats = _format_options(info)
        if not formats:
            raise DownloadError("未提取到可下载的媒体格式，请确认 Cookie 仍有效并稍后重试")
        result = {
            "url": url,
            "video_id": info.get("id"),
            "title": info.get("title") or "未命名视频",
            "channel": info.get("channel") or info.get("uploader") or "",
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail") or "",
            "formats": formats,
        }
        self._cache[url] = (time.time(), result)
        while len(self._cache) > 20:
            self._cache.popitem(last=False)
        return result


class DownloadManager:
    def __init__(self) -> None:
        self.tasks: OrderedDict[str, Task] = OrderedDict()
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.worker: asyncio.Task[None] | None = None
        self._last_job_finished = 0.0

    async def start(self) -> None:
        if self.worker is None or self.worker.done():
            self.worker = asyncio.create_task(self._work(), name="tubesafe-download-worker")

    async def stop(self) -> None:
        for process in self.processes.values():
            process.terminate()
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass

    def add(self, url: str, title: str, format_id: str, format_label: str) -> Task:
        task = Task(
            id=uuid.uuid4().hex[:12],
            url=normalize_youtube_url(url),
            title=title[:240] or "未命名视频",
            format_id=format_id[:160],
            format_label=format_label[:40],
        )
        _task_log(task, f"queued: {task.title}\nformat={task.format_id}")
        self.tasks[task.id] = task
        self.queue.put_nowait(task.id)
        return task

    async def cancel(self, task_id: str) -> Task:
        task = self.get(task_id)
        if task.status in {"completed", "failed", "cancelled"}:
            return task
        task.status = "cancelled"
        task.detail = "已取消"
        task.updated_at = time.time()
        _task_log(task, "cancelled: 用户取消任务")
        process = self.processes.get(task_id)
        if process and process.returncode is None:
            process.terminate()
        return task

    def remove(self, task_id: str) -> None:
        task = self.get(task_id)
        if task.status in {"downloading", "merging"}:
            raise DownloadError("运行中的任务请先取消")
        if task.file_path:
            path = Path(task.file_path)
            download_root = Path(Settings.load().download_dir).resolve()
            try:
                path.resolve().relative_to(download_root)
                path.unlink(missing_ok=True)
            except (ValueError, OSError):
                pass
        del self.tasks[task_id]

    def get(self, task_id: str) -> Task:
        try:
            return self.tasks[task_id]
        except KeyError:
            raise DownloadError("未找到该任务") from None

    async def _work(self) -> None:
        while True:
            task_id = await self.queue.get()
            task = self.tasks.get(task_id)
            if task is None or task.status == "cancelled":
                self.queue.task_done()
                continue
            settings = Settings.load()
            cooldown = max(0.0, settings.sleep_min - (time.time() - self._last_job_finished))
            if cooldown:
                task.detail = "请求间隔保护"
                await asyncio.sleep(cooldown + random.uniform(0, 1.5))
            try:
                await self._download(task, settings)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if task.status != "cancelled":
                    task.status = "failed"
                    task.error = _friendly_error(str(exc))
                    task.detail = "下载失败"
                    task.updated_at = time.time()
            finally:
                self.processes.pop(task_id, None)
                self._last_job_finished = time.time()
                self.queue.task_done()

    async def _download(self, task: Task, settings: Settings) -> None:
        _task_log(task, f"starting: cookies={settings.cookies_browser or ('file' if settings.cookies_path else 'none')}; format={task.format_id}")
        try:
            for downloader in ("aria2c", "native"):
                code, detail = await self._download_attempt(task, settings, downloader)
                if task.status == "cancelled":
                    _task_log(task, "cancelled")
                    return
                if not code:
                    break
                # aria2 的 22 可能包裹真正的 HTTP 原因；限流时不额外重试。
                if (downloader == "aria2c" and "aria2c exited with code 22" in detail
                        and "429" not in detail and "too many requests" not in detail.lower()):
                    task.detail = "外部下载器响应异常，切换内置下载器重试"
                    _task_log(task, "retry: aria2c HTTP response error; switching to native (once)")
                    continue
                raise DownloadError(_friendly_error(detail))
            if not task.file_path or not Path(task.file_path).is_file():
                raise DownloadError("下载完成但未找到输出文件")
            task.status = "completed"
            task.progress = 100
            task.detail = "文件已就绪"
            task.updated_at = time.time()
            _task_log(task, f"completed: {task.file_path}")
        except asyncio.CancelledError:
            _task_log(task, "cancelled: 服务停止或任务被中断")
            raise
        except Exception as exc:
            detail = _friendly_error(str(exc))
            _task_log(task, f"failed: {detail}")
            logger.error("Task %s failed: %s; log: %s", task.id, detail, task_log_path(task.id))
            raise
        finally:
            self.processes.pop(task.id, None)

    async def _download_attempt(self, task: Task, settings: Settings, downloader: str) -> tuple[int, str]:
        download_dir = Path(settings.download_dir)
        download_dir.mkdir(parents=True, exist_ok=True)
        task.status = "downloading"
        task.detail = "下载媒体流"
        task.updated_at = time.time()
        task.progress = 0
        task.speed = task.eta = task.file_path = ""
        _task_log(task, f"downloader={downloader}")

        aria_args = (
            f"aria2c:-x {settings.connections} -s {settings.connections} -k 1M "
            "--max-tries=5 --retry-wait=3 --file-allocation=none --summary-interval=0"
        )
        args = _common_args(settings) + [
            "--newline",
            "--no-quiet",
            "--progress",
            "--progress-template",
            "download:PROGRESS:%(progress._percent_str)s|%(progress._speed_str)s|%(progress._eta_str)s",
            "--print",
            "after_move:FILE:%(filepath)s",
            "--concurrent-fragments",
            "1",
            "--external-downloader",
            downloader,
            "--external-downloader-args",
            aria_args,
            "--merge-output-format",
            "mp4",
            "--paths",
            str(download_dir),
            "--output",
            "%(title)s.%(ext)s",
            "--format",
            task.format_id,
            task.url,
        ]
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        self.processes[task.id] = process
        assert process.stdout
        lines: deque[str] = deque(maxlen=40)
        errors: deque[str] = deque(maxlen=20)
        async for raw_line in process.stdout:
            line = ANSI_RE.sub("", raw_line.decode("utf-8", "replace")).strip()
            _task_log(task, line)
            if not line:
                continue
            safe_line = _redact_output(line)
            lines.append(safe_line)
            if re.search(r"error|status=[45]\d\d|forbidden|too many requests", safe_line, re.I):
                errors.append(safe_line)
            match = PROGRESS_RE.search(line.replace(" ", ""))
            if match:
                task.progress = min(99.0, float(match.group("percent")))
                task.speed = match.group("speed")
                task.eta = match.group("eta")
                task.updated_at = time.time()
            elif "Merging formats" in line or "Merger" in line or "Fixing" in line:
                task.status = "merging"
                task.detail = "合并音视频"
                task.progress = max(task.progress, 99)
            elif line.startswith("FILE:"):
                task.file_path = line[5:]
        code = await process.wait()
        _task_log(task, f"downloader={downloader} exit_code={code}")
        return code, "\n".join(errors or lines) or "下载进程异常退出"
