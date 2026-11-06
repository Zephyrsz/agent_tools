从 MP4 里抽取音频，开源方案很多，按类型整理一下：

相关交付物：[`INSTALL.md`](INSTALL.md)（安装和使用）、[`DESIGN.md`](DESIGN.md)（设计说明）、[`extract_media.sh`](extract_media.sh)（同时导出视频 MP4 和音频 M4A）。

## FFmpeg 实测

测试文件：`~/Downloads/7月9日丧失清道夫视频.mp4`（约 7.3 GB，H.264 视频 + AAC 音频）。

AAC 音轨适合直接封装为 `.m4a`，不需要重新编码：

```bash
ffmpeg -i "$HOME/Downloads/7月9日丧失清道夫视频.mp4" \
  -map 0:a:0 -vn -c:a copy -movflags +faststart \
  "video_tools/7月9日丧失清道夫视频.m4a"
```

本次导出已验证通过：输出约 153 MB，AAC-LC、44.1 kHz、立体声，时长 `01:46:39.85`，并已完成完整解码检查。

## 命令行工具

**FFmpeg**（最常用、最灵活）
```bash
# 直接拷贝音频流，不重新编码，速度最快；AAC 音轨推荐使用 .m4a 容器
ffmpeg -i input.mp4 -map 0:a:0 -vn -c:a copy output.m4a

# 转成 mp3
ffmpeg -i input.mp4 -vn -acodec libmp3lame -q:a 2 output.mp3

# 转成无损 wav
ffmpeg -i input.mp4 -vn -acodec pcm_s16le -ar 44100 output.wav
```
`-vn` 是去掉视频流，`copy` 模式不重编码保留原始质量，速度最快。

**libav / avconv**：FFmpeg 的一个分支，命令类似，现在用得少了，FFmpeg 已经是事实标准。

## Python 库（适合批量处理或集成到 pipeline）

- **moviepy**：`VideoFileClip(path).audio.write_audiofile(out)`，接口简单，但底层还是调 FFmpeg，大批量处理效率一般。
- **pydub**：主要做音频处理，配合 ffmpeg 后端也能做提取。
- 如果只是提取，直接用 `ffmpeg-python`（FFmpeg 的 Python 封装）或者 subprocess 调 ffmpeg 命令效率最高，这也是大多数生产环境的做法。

## GUI 工具

- **Audacity**：不直接支持导入 mp4，需要先装 FFmpeg 库（Audacity 里有个 FFmpeg import/export 插件），装好后可以直接拖 mp4 进去再导出音频。
- **VLC**：菜单里有"转换/保存"功能，可以选择只输出音频格式，图形界面下最省事。
- **HandBrake**：主要做视频转码，但也可以设置输出为纯音轨。
- **Shotcut / OpenShot**：非线性视频编辑器，导入后直接导出音频轨。

## 建议

如果是单次/少量提取，FFmpeg 一行命令最快；如果要批量或者集成进 pipeline（比如你现在在做的 EDL 音频编辑器工作流），直接用 subprocess 调 FFmpeg 或者 ffmpeg-python 封装会比 moviepy 更省资源，尤其是大文件场景下 `-c:a copy` 不重编码几乎是瞬间完成。
