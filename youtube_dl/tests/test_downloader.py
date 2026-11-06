import asyncio
import pytest

from app import downloader
from app.core import Settings


class ProcessOutput:
    def __init__(self, lines, code):
        self.stdout = self.stream(lines)
        self.returncode = code

    async def stream(self, lines):
        for line in lines:
            yield (line + "\n").encode()

    async def wait(self):
        return self.returncode


def setup_download(monkeypatch, tmp_path, outputs):
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        lines, code = outputs[len(calls) - 1]
        return ProcessOutput(lines, code)

    monkeypatch.setattr(downloader.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(downloader, "TASK_LOG_DIR", tmp_path / "logs", raising=False)
    task = downloader.Task("abcdef123456", "https://www.youtube.com/watch?v=0Zy8bksnKVs", "Audio", "bestaudio[ext=m4a]/bestaudio", "仅音频")
    return downloader.DownloadManager(), task, calls


def test_aria_http_error_retries_native_and_keeps_complete_private_log(monkeypatch, tmp_path):
    output = tmp_path / "audio.m4a"
    output.write_bytes(b"audio")
    lines = [f"line {i}" for i in range(60)] + [
        "URI=https://media.googlevideo.com/videoplayback?sig=secret-token",
        "Cookie: secret-cookie",
        "Authorization: Bearer secret-auth",
        "errorCode=22 The response status is not successful. status=403",
        "ERROR: aria2c exited with code 22",
    ]
    manager, task, calls = setup_download(monkeypatch, tmp_path, [(lines, 1), ([f"FILE:{output}"], 0)])
    settings = Settings(download_dir=str(tmp_path), cookies_browser="chrome", proxy_url="http://user:secret-pass@localhost:1234")
    asyncio.run(manager._download(task, settings))
    assert task.status == "completed"
    assert len(calls) == 2
    assert calls[0][calls[0].index("--external-downloader") + 1] == "aria2c"
    assert calls[1][calls[1].index("--external-downloader") + 1] == "native"
    for args in calls:
        assert args[args.index("--cookies-from-browser") + 1] == "chrome"
        assert args[args.index("--format") + 1] == task.format_id
        assert "--restrict-filenames" not in args
        assert args[args.index("--output") + 1] == "%(title)s.%(ext)s"
    log = tmp_path / "logs" / f"{task.id}.log"
    text = log.read_text()
    assert "line 0" in text and "line 59" in text
    assert "status=403" in text and "native" in text and "completed" in text
    assert not any(secret in text for secret in ("secret-token", "secret-cookie", "secret-auth", "secret-pass"))
    assert log.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("status", [403, 429])
def test_http_cause_survives_generic_aria_error(monkeypatch, tmp_path, status):
    lines = [f"errorCode=22 status={status}", "ERROR: aria2c exited with code 22"]
    outputs = [(lines, 1), ([f"ERROR: HTTP Error {status}"], 1)]
    manager, task, calls = setup_download(monkeypatch, tmp_path, outputs)
    with pytest.raises(downloader.DownloadError, match=str(status)):
        asyncio.run(manager._download(task, Settings(download_dir=str(tmp_path))))
    assert len(calls) == (1 if status == 429 else 2)
    assert "failed" in (tmp_path / "logs" / f"{task.id}.log").read_text()


def test_other_aria_failure_is_not_retried(monkeypatch, tmp_path):
    manager, task, calls = setup_download(monkeypatch, tmp_path, [(["ERROR: aria2c exited with code 9"], 1)])
    with pytest.raises(downloader.DownloadError, match="code 9"):
        asyncio.run(manager._download(task, Settings(download_dir=str(tmp_path))))
    assert len(calls) == 1


def test_cancelled_download_is_logged_without_retry(monkeypatch, tmp_path):
    manager, task, calls = setup_download(monkeypatch, tmp_path, [])

    async def cancelled_spawn(*args, **kwargs):
        calls.append(args)
        task.status = "cancelled"
        return ProcessOutput(["ERROR: aria2c exited with code 22"], 1)

    monkeypatch.setattr(downloader.asyncio, "create_subprocess_exec", cancelled_spawn)
    asyncio.run(manager._download(task, Settings(download_dir=str(tmp_path))))
    assert task.status == "cancelled" and len(calls) == 1
    assert "cancelled" in (tmp_path / "logs" / f"{task.id}.log").read_text()


def test_task_log_remains_accessible_after_restart(monkeypatch, tmp_path):
    import httpx
    from app.main import app

    monkeypatch.setattr(downloader, "TASK_LOG_DIR", tmp_path, raising=False)
    (tmp_path / "abcdef123456.log").write_text("retained task output")
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/api/tasks/abcdef123456/log")
            assert response.status_code == 200
            assert response.text == "retained task output"
            assert (await client.get("/api/tasks/000000000000/log")).status_code == 404
            assert (await client.get("/api/tasks/not-a-task/log")).status_code == 404

    asyncio.run(check())
