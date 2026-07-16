# TubeSafe

仅供个人本机使用的 YouTube 视频下载工具。使用 `yt-dlp` 解析，`aria2c` 以保守连接数下载，`ffmpeg` 在本地合并分离的音视频流。

> 仅下载你有权保存的内容，并遵守 YouTube 服务条款及所在地法律。Cookie 与代理凭据均保存在本机；请勿分享配置文件。

## 启动

本机需要安装 `aria2c` 与 `ffmpeg`。首次运行：

```bash
cd /Users/rgwei/pj/pj_agent/agent_tools/youtube_dl
uv sync --extra dev
uv run tubesafe
```

在浏览器打开 <http://127.0.0.1:8765>。服务固定监听回环地址，不会暴露到局域网。

## 风控默认值

- 同时只执行 1 个下载任务。
- `aria2c` 最多使用 4 个媒体连接。
- 解析和任务之间加入 3–7 秒随机等待。
- 解析、分片和提取失败采用有限重试；429、403 和身份验证错误会转成可操作提示。
- `googlevideo` 媒体直链不返回前端，解析与下载使用同一网络出口。
- 使用本机 Node.js 和 `yt-dlp` 官方推荐的 `ejs:github` 远程组件解决 YouTube 播放器 JS 挑战；组件由 `yt-dlp` 获取并缓存。

如 YouTube 要求验证身份，可在页面中选择一个已登录 YouTube 的本机浏览器，`yt-dlp` 会直接读取该浏览器的 Cookie；也可通过页面加载 Netscape 格式的 `cookies.txt`。加载的文件会复制到 `~/.config/tubesafe/cookies.txt` 并设置为仅当前用户可读写，API 不会回显 Cookie 内容。浏览器 Cookie 可能触发 macOS 钥匙串授权提示。代理应仅使用你拥有或获准使用的网络出口；频繁轮换代理可能增加验证风险。

## 文件位置

默认保存到 `~/Downloads/TubeSafe`。本地配置写入 `~/.config/tubesafe/config.json`，权限设置为仅当前用户可读写。

## 测试

```bash
uv run pytest
```
