# macOS 备忘录工具

一个操作当前 Mac 登录用户 Apple Notes（备忘录）的本地 Python 工具，提供：

- Python API：NotesClient
- 命令行：mac-notes
- HTTP API：FastAPI + OpenAPI 文档
- 账户与文件夹列表
- 备忘录元数据列表、按标题过滤、分页
- 按 Notes ID 读取纯文本和 HTML
- 新建备忘录
- 替换或追加已有备忘录内容

Apple Notes 不是普通文件系统，工具以 Notes 返回的 ID 作为单条备忘录的稳定标识。底层使用 macOS 自带的 JavaScript for Automation，不读取或修改 Notes 的私有数据库。

## 环境要求

- macOS
- Python 3.11+
- Apple Notes 已登录至少一个账户

首次访问时，macOS 会询问终端或 Python 是否允许控制“备忘录”，请选择允许。也可以在“系统设置 > 隐私与安全性 > 自动化”中管理权限。

## 安装与启动

~~~bash
cd /Users/rgwei/pj/pj_agent/agent_tools/mac_notes
uv sync --extra dev

# 检查 Notes 连接；首次运行会触发系统权限提示
uv run mac-notes health

# 启动 HTTP API
uv run mac-notes serve
~~~

服务固定监听 http://127.0.0.1:8766，交互式 API 文档位于：

- Swagger UI：<http://127.0.0.1:8766/docs>
- OpenAPI JSON：<http://127.0.0.1:8766/openapi.json>

服务只接受本机 Host 与 Origin。不要通过反向代理、端口转发或把监听地址改为 0.0.0.0 对外暴露，因为 API 具有当前用户的备忘录写权限。

## HTTP API

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | /api/health | 检查 Notes 权限和默认账户 |
| GET | /api/accounts | 列出账户 |
| GET | /api/folders | 列出文件夹 |
| GET | /api/notes | 列出备忘录元数据 |
| GET | /api/notes/{note_id} | 读取一条备忘录 |
| POST | /api/notes | 新建备忘录 |
| PUT | /api/notes/{note_id} | 替换或追加内容 |

列出最近修改的备忘录：

~~~bash
curl 'http://127.0.0.1:8766/api/notes?limit=20'
~~~

列出指定账户和文件夹；同名文件夹建议传列表返回的 folder_id：

~~~bash
curl --get 'http://127.0.0.1:8766/api/notes' \
  --data-urlencode 'account=iCloud' \
  --data-urlencode 'folder=工作/项目' \
  --data-urlencode 'recursive=true'
~~~

读取备忘录。Notes ID 通常包含斜杠，因此需要进行 URL 编码：

~~~bash
NOTE_ID='x-coredata://...'
ENCODED_NOTE_ID="$(python3 -c \
  'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' \
  "$NOTE_ID")"
curl "http://127.0.0.1:8766/api/notes/$ENCODED_NOTE_ID"
~~~

返回值同时包含便于程序处理的 plaintext 和保留格式的 body_html。

创建纯文本备忘录：

~~~bash
curl -X POST 'http://127.0.0.1:8766/api/notes' \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "项目记录",
    "content": "第一行\n第二行",
    "content_format": "text",
    "folder": "工作"
  }'
~~~

向已有备忘录追加内容：

~~~bash
curl -X PUT "http://127.0.0.1:8766/api/notes/$ENCODED_NOTE_ID" \
  -H 'Content-Type: application/json' \
  -d '{"content":"新增一行","mode":"append","content_format":"text"}'
~~~

content_format 默认为 text，工具会安全转义 HTML 字符。只有调用方明确需要 Notes 富文本格式且信任输入时才使用 html。

## 命令行

~~~bash
# 账户和文件夹
uv run mac-notes accounts
uv run mac-notes folders --account iCloud

# 列表和读取
uv run mac-notes list --folder '工作/项目' --recursive --limit 20
uv run mac-notes read 'x-coredata://...'

# 从参数创建
uv run mac-notes create \
  --title '项目记录' \
  --content $'第一行\n第二行' \
  --folder '工作'

# 从 UTF-8 / HTML 文件创建
uv run mac-notes create \
  --title '周报' \
  --content-file ./weekly.html \
  --format html

# 替换或追加
uv run mac-notes update 'x-coredata://...' \
  --content-file ./replacement.txt
uv run mac-notes update 'x-coredata://...' \
  --content '新增内容' \
  --mode append
~~~

## Python API

~~~python
from mac_notes import NotesClient

notes = NotesClient()

items = notes.list_notes(folder="工作", recursive=True, limit=20)
detail = notes.get_note(items[0]["id"])

created = notes.create_note(
    title="API 创建的记录",
    content="正文内容",
    folder="工作",
)
notes.update_note(created["id"], "追加内容", mode="append")
~~~

## 测试

~~~bash
cd /Users/rgwei/pj/pj_agent/agent_tools/mac_notes
uv run pytest
~~~

自动测试使用假的 Notes 执行器，不会读取或写入真实备忘录。

## 限制

- 密码锁定的备忘录必须先在 Notes 中解锁；未解锁时正文可能为空或读取失败。
- 附件、扫描件、表格、清单等复杂内容可通过 body_html 保留一部分结构，但本工具不提供附件上传接口。
- 标题由 Notes 根据正文第一行生成。替换操作默认保留现有标题，传 preserve_title=false 可完整替换 HTML 正文。
- HTTP 服务适合当前登录用户的本机自动化，不适合作为多用户或远程服务。
