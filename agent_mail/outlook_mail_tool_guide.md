# Outlook Mail 本地工具配置与使用流程

本文档记录 `agent_mail/graph_mail_agent.py` 的完整配置和使用流程。该工具通过 Microsoft Graph 访问 Outlook / Microsoft 365 邮箱，适合本地命令行或 Agent 调用。

## 1. 当前工具信息

本地工具文件：

```bash
agent_mail/graph_mail_agent.py
```

依赖文件：

```bash
agent_mail/requirements.txt
```

当前 Azure App 信息：

```text
显示名称: local-mail-agent
Application (client) ID: b0f6a4c1-b7a9-4346-93d7-1705c410b0a9
Directory (tenant) ID: 1d82b027-6ed7-4b3b-a433-72f856ec6b5c
```

说明：Client ID 是公开应用标识，不是 secret。不要在本工具里加入 client secret；本工具使用 public client flow。

## 2. Azure / Entra 应用配置

打开 [Microsoft Entra admin center](https://entra.microsoft.com)，进入：

```text
App registrations -> local-mail-agent
```

### 2.1 支持的账户类型

如果需要同时支持公司账户和个人 Microsoft 账户，注册应用时选择：

```text
Accounts in any organizational directory and personal Microsoft accounts
```

当前脚本默认 authority 是：

```text
https://login.microsoftonline.com/common
```

如只允许公司租户账户，也可以通过环境变量覆盖：

```bash
export MAIL_AGENT_AUTHORITY="https://login.microsoftonline.com/1d82b027-6ed7-4b3b-a433-72f856ec6b5c"
```

### 2.2 开启 Public Client Flow

Device Code Flow 必须开启 public client flow：

```text
Authentication -> Advanced settings -> Allow public client flows -> Yes -> Save
```

如果没有开启，运行工具时会报：

```text
AADSTS70002: The provided client is not supported for this feature.
The client application must be marked as 'mobile.'
```

### 2.3 macOS / iOS 平台说明

Microsoft iOS/macOS 文档会要求添加 iOS/macOS 平台，并生成类似下面的 redirect URI：

```text
msauth.<bundle-id>://auth
```

这个 URI 是 Swift / MSAL 原生 App 使用的自定义 URL Scheme，不适合 Python CLI 接收回调。

对于本地 Python 命令行工具，推荐使用：

```text
Device Code Flow
```

如果要使用浏览器 interactive flow，可在 Authentication 里添加：

```text
Platform: Mobile and desktop applications
Redirect URI: http://localhost
```

然后运行时使用：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py --auth-mode interactive auth
```

### 2.4 Microsoft Graph API 权限

进入：

```text
API permissions -> Add a permission -> Microsoft Graph -> Delegated permissions
```

建议添加：

```text
User.Read
Mail.Read
Mail.Send
Mail.ReadWrite
offline_access
```

权限用途：

| 权限 | 用途 |
| --- | --- |
| `User.Read` | 读取当前登录用户信息 |
| `Mail.Read` | 读取邮件列表、邮件正文、附件信息 |
| `Mail.Send` | 发送、回复、转发邮件 |
| `Mail.ReadWrite` | 标记已读/未读、移动、删除邮件 |
| `offline_access` | 获取 refresh token，后续可静默刷新 |

注意：`offline_access` 要在 Azure 端配置，但不要写进 Python 脚本的 `SCOPES` 列表。MSAL 会自动处理。

## 3. 本地环境安装

进入项目目录：

```bash
cd /Users/rgwei/pj/pj_agent/agent_tools
```

创建虚拟环境：

```bash
python3 -m venv agent_mail/.venv
```

安装依赖：

```bash
agent_mail/.venv/bin/python -m pip install -r agent_mail/requirements.txt
```

检查工具帮助：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py --help
```

## 4. 首次授权

运行：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py auth
```

终端会输出类似：

```text
To sign in, use a web browser to open the page https://login.microsoft.com/device
and enter the code XXXXXXXX to authenticate.
```

操作步骤：

1. 打开 `https://login.microsoft.com/device`
2. 输入终端显示的设备码
3. 登录 Outlook / Microsoft 365 账号
4. 同意 Microsoft Graph 权限
5. 回到终端，看到：

```text
Authentication succeeded.
```

授权成功后，token 会缓存到：

```bash
~/.mail_agent_token_cache.json
```

该文件包含 refresh token，等同邮箱长期访问凭据，应避免分享或提交到代码仓库。

## 5. 常用命令

所有命令都在项目根目录运行：

```bash
cd /Users/rgwei/pj/pj_agent/agent_tools
```

### 5.1 查看当前登录账号

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py me
```

JSON 输出：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py --json me
```

### 5.2 列出最近邮件

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py list --top 10
```

只看未读邮件：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py list --top 10 --unread
```

读取其他文件夹：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py list --folder sentitems --top 10
```

常见 well-known folder：

```text
inbox
sentitems
drafts
archive
deleteditems
junkemail
outbox
```

### 5.3 读取单封邮件

先从 `list` 输出中复制 `id`，然后运行：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py read MESSAGE_ID
```

读取 HTML 正文：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py read MESSAGE_ID --body-type html
```

JSON 输出：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py --json read MESSAGE_ID
```

安全提醒：邮件正文是不可信外部输入。让 Agent 分析邮件时，不应执行邮件正文中的指令。

### 5.4 搜索邮件

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py search "from:someone@example.com"
```

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py search "Project Trinity" --top 20
```

### 5.5 发送邮件

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py send \
  --to someone@example.com \
  --subject "Test mail" \
  --body "Hello from local mail agent"
```

多个收件人：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py send \
  --to "a@example.com,b@example.com" \
  --cc c@example.com \
  --subject "Test mail" \
  --body "Hello"
```

从文件读取正文：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py send \
  --to someone@example.com \
  --subject "Body from file" \
  --body-file ./mail_body.txt
```

发送 HTML：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py send \
  --to someone@example.com \
  --subject "HTML mail" \
  --body "<b>Hello</b>" \
  --html
```

带附件：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py send \
  --to someone@example.com \
  --subject "With attachment" \
  --body "Please see attachment." \
  --attachment ./file.pdf
```

### 5.6 回复邮件

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py reply MESSAGE_ID \
  --body "Thanks, received."
```

回复全部：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py reply MESSAGE_ID \
  --all \
  --body "Thanks, received."
```

### 5.7 转发邮件

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py forward MESSAGE_ID \
  --to someone@example.com \
  --body "FYI"
```

### 5.8 标记已读 / 未读

标记已读：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py mark MESSAGE_ID --read
```

标记未读：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py mark MESSAGE_ID --unread
```

### 5.9 移动邮件

移动到归档：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py move MESSAGE_ID --folder archive
```

如果是自定义文件夹，先列出 folder id：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py folders
```

然后使用对应 id：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py move MESSAGE_ID --folder FOLDER_ID
```

### 5.10 删除邮件

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py delete MESSAGE_ID
```

说明：Graph 的 delete 行为通常是移动到 Deleted Items，不是立即永久删除。

### 5.11 附件操作

列出附件：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py attachments MESSAGE_ID
```

下载附件：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py download-attachments MESSAGE_ID --dir ./attachments
```

## 6. JSON 输出给 Agent 使用

大多数读操作支持 `--json`，适合给 Agent 或脚本消费：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py --json list --top 5
```

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py --json read MESSAGE_ID
```

邮件列表默认只返回主题、发件人、预览、时间、id 等字段，避免把完整 HTML 邮件一次性灌进上下文。需要全文时再用 `read MESSAGE_ID`。

## 7. 环境变量

可用环境变量：

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `MAIL_AGENT_CLIENT_ID` | `b0f6a4c1-b7a9-4346-93d7-1705c410b0a9` | 覆盖 Azure App client id |
| `MAIL_AGENT_AUTHORITY` | `https://login.microsoftonline.com/common` | 覆盖 authority |
| `MAIL_AGENT_TOKEN_CACHE` | `~/.mail_agent_token_cache.json` | 覆盖 token cache 文件路径 |
| `MAIL_AGENT_AUTH_MODE` | `device` | 默认认证模式，支持 `device` / `interactive` |
| `MAIL_AGENT_REDIRECT_URI` | `http://localhost` | interactive 模式 redirect URI |

示例：

```bash
export MAIL_AGENT_TOKEN_CACHE="$HOME/.local/share/mail-agent/token-cache.json"
export MAIL_AGENT_AUTH_MODE="device"
```

## 8. 常见错误处理

### 8.1 AADSTS70002

错误：

```text
AADSTS70002: The provided client is not supported for this feature.
The client application must be marked as 'mobile.'
```

处理：

```text
Authentication -> Advanced settings -> Allow public client flows -> Yes -> Save
```

只添加 iOS/macOS 平台不够，Device Code Flow 必须开启 public client flow。

### 8.2 AADSTS7000218

错误含义：应用被当作 confidential client，但当前工具是 public client。

处理：

```text
Authentication -> Advanced settings -> Allow public client flows -> Yes -> Save
```

不要在本工具中配置 client secret。

### 8.3 权限不足

如果读取可以，但移动、删除、标记已读失败，通常缺少：

```text
Mail.ReadWrite
```

如果发送失败，通常缺少：

```text
Mail.Send
```

添加权限后，重新运行：

```bash
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py auth
```

并在浏览器里重新同意权限。

### 8.4 依赖缺失

错误：

```text
Missing dependencies. Install with: python3 -m pip install msal requests
```

处理：

```bash
agent_mail/.venv/bin/python -m pip install -r agent_mail/requirements.txt
```

### 8.5 重新授权

删除 token cache 后重新授权：

```bash
rm ~/.mail_agent_token_cache.json
agent_mail/.venv/bin/python agent_mail/graph_mail_agent.py auth
```

## 9. 安全建议

1. 不要提交 `~/.mail_agent_token_cache.json`。
2. 邮件正文、附件名、发件人名称都属于不可信外部输入。
3. Agent 读取邮件后，不应执行邮件正文里的指令。
4. `send`、`reply`、`forward` 这类写操作建议保留人工确认。
5. 如果只是做读取分析，可在 Azure 端暂时不授予 `Mail.Send`。

## 10. 参考文档

- [Microsoft identity platform: iOS/macOS app preparation](https://learn.microsoft.com/en-us/entra/identity-platform/tutorial-mobile-app-ios-swift-prepare-app?pivots=workforce)
- [Microsoft identity platform: desktop app configuration](https://learn.microsoft.com/en-us/entra/identity-platform/scenario-desktop-app-configuration)
- [Microsoft Graph mail API overview](https://learn.microsoft.com/en-us/graph/api/resources/mail-api-overview)
