# 安装文档

## 依赖

脚本依赖 Bash、FFmpeg 和 `ffprobe`。`ffprobe` 会随 FFmpeg 一起安装，用于在导出前检查输入文件是否同时包含视频流和音频流。

建议使用 FFmpeg 4.4 或更高版本。本次实测环境为 FFmpeg 8.1。

## macOS

使用 Homebrew 安装：

```bash
brew install ffmpeg
```

验证安装：

```bash
ffmpeg -version
ffprobe -version
```

## Ubuntu / Debian

```bash
sudo apt update
sudo apt install ffmpeg
```

## Windows

Shell 脚本需要在 WSL 或 Git Bash 中运行。如果系统已安装 `winget`，可以先在 PowerShell 中安装 FFmpeg：

```powershell
winget install Gyan.FFmpeg.Shared
```

安装后重新打开终端，并确认 WSL 或 Git Bash 可以找到 `ffmpeg` 和 `ffprobe`。

## 安装脚本权限

在仓库根目录执行：

```bash
chmod +x video_tools/extract_media.sh
```

脚本不需要 Python 或 Node.js。

## 快速使用

默认输出到 `video_tools/`：

```bash
video_tools/extract_media.sh \
  "$HOME/Downloads/7月9日丧失清道夫视频.mp4"
```

也可以显式指定输出目录：

```bash
video_tools/extract_media.sh \
  "$HOME/Downloads/7月9日丧失清道夫视频.mp4" \
  video_tools/output
```

脚本会生成：

```text
7月9日丧失清道夫视频.video.mp4  # 仅视频流
7月9日丧失清道夫视频.m4a        # 仅音频流
```

默认不会覆盖已有文件。确认要替换时使用：

```bash
video_tools/extract_media.sh --force input.mp4 video_tools/output
```

## 本次实测

使用 `~/Downloads/7月9日丧失清道夫视频.mp4` 完整运行脚本，得到：

| 文件 | 媒体流 | 大小 | 时长 |
| --- | --- | --- | --- |
| `7月9日丧失清道夫视频.video.mp4` | H.264，1998×1080，30 fps | 约 7.1 GB | `01:46:39.83` |
| `7月9日丧失清道夫视频.m4a` | AAC-LC，44.1 kHz，立体声 | 约 153 MB | `01:46:39.85` |

两个输出均已通过 FFmpeg 完整读取检查。

## 故障排查

- `ffmpeg is not installed`：按上面的系统说明安装，并确认命令在 `PATH` 中。
- `Input has no video stream` 或 `Input has no audio stream`：输入文件不包含对应媒体流，脚本不会生成不完整输出。
- 磁盘空间不足：视频输出通常接近源视频大小；音频输出大小取决于音轨码率和时长。
- 目标文件已存在：不加 `--force` 时脚本会停止，以避免意外覆盖。
