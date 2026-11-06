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

### 后台运行

在项目目录执行（首次启动需要安装 `uv`，脚本会按 `uv.lock` 自动同步 Python 依赖）：

```bash
./start.sh start    # 后台启动，重复执行不会重复启动
./start.sh status   # 查看运行状态
./start.sh stop     # 停止服务
./start.sh restart  # 停止后重新启动
```

脚本可从任意工作目录通过完整路径执行。默认端口为 `8765`，可用
`PORT=8877 ./start.sh start` 或 `PORT=8877 ./start.sh restart` 指定其他端口。
`stop` 和 `status` 自动读取已记录的端口；`restart` 未指定 `PORT` 时使用默认端口。
每个项目目录仅管理一个实例，不接管手动运行的 `uv run tubesafe` 服务。

日志追加写入 `logs/tubesafe.log`，进程记录保存在 `.run/tubesafe.pid`，均不会提交到 Git。
可用 `tail -f logs/tubesafe.log` 查看日志。停止时会等待最多 30 秒让服务正常退出，
超时会报告错误并保留进程记录。重启会中断正在进行的下载，内存中的任务列表不会保留。
缺少 `aria2c`、`ffmpeg` 或 Node.js 时脚本会提示，下载前请安装这些工具。

### 下载诊断与任务日志

每个任务从入队开始写入 `logs/tasks/<任务编号>.log`，包含下载器的完整输出、
警告、进度、退出码，以及切换下载器、完成或失败记录。页面的「下载日志」可保存该文件；
日志在重启服务或删除任务后仍保留，也可通过 `/api/tasks/<任务编号>/log` 获取。
日志文件仅当前用户可读写，Cookie、授权头、代理 URL 和媒体签名 URL 会被遮蔽。
日志不会自动清理，需要时可手动删除旧文件。

默认使用 `aria2c`；遇到其 HTTP 响应错误（退出码 22）时，会使用相同格式和
Cookie/代理设置切换到 `yt-dlp` 内置下载器，最多切换一次。若检测到 429 限流则不切换。
页面错误优先显示真实 HTTP 原因，不再只显示 `aria2c exited with code 22`。
选择「Chrome」作为 Cookie 来源后，可选「仅音频」进行验证。

下载文件以视频标题作为文件名，保留中文、空格和原始扩展名，例如
`2026-09-30 乃木坂46のオールナイトニッポン - 井上和 (乃木坂46).m4a`。
同名文件会由 yt-dlp 自动加编号，文件名中系统不允许的字符会被替换。

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
