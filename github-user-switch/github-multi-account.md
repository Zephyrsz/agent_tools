# 本地管理多个 GitHub 账户

## 1. 先区分提交身份与认证身份

Git 在本地涉及两类相互独立的身份：

- **提交身份**：由 `user.name` 和 `user.email` 决定，显示在 commit 作者信息中。
- **认证身份**：由 SSH 密钥、GitHub CLI 或 HTTPS Token 决定，用于判断是否有权拉取和推送仓库。

只修改 `user.name` 并不会切换 GitHub 登录账户；只切换 GitHub 登录账户也不会自动修正 commit 作者信息。

推荐配置方式：

1. 每个 GitHub 账户使用一把独立 SSH 密钥。
2. 在 `~/.ssh/config` 中为每个账户设置不同的 Host 别名。
3. 在每个项目中单独设置 `user.name` 和 `user.email`。
4. HTTPS 和 `gh auth switch` 仅用于临时切换或辅助管理。

## 2. 推荐方案：使用多套 SSH 密钥

假设本机需要使用两个账户：

| 用途 | GitHub 用户 | SSH Host 别名 |
| --- | --- | --- |
| 个人项目 | `personal-user` | `github-personal` |
| 公司项目 | `xgame3141` | `github-zkcare` |

### 2.1 生成独立密钥

```bash
ssh-keygen -t ed25519 -C "personal@example.com" -f ~/.ssh/id_ed25519_personal
ssh-keygen -t ed25519 -C "work@example.com" -f ~/.ssh/id_ed25519_zkcare
```

不要覆盖已有密钥，也不要把私钥文件上传到 GitHub 或提交到仓库。

在 macOS 中把密钥加入 `ssh-agent` 和钥匙串：

```bash
ssh-add --apple-use-keychain ~/.ssh/id_ed25519_personal
ssh-add --apple-use-keychain ~/.ssh/id_ed25519_zkcare
```

### 2.2 将公钥添加到对应 GitHub 账户

分别读取公钥：

```bash
pbcopy < ~/.ssh/id_ed25519_personal.pub
pbcopy < ~/.ssh/id_ed25519_zkcare.pub
```

每次复制后，登录对应 GitHub 账户，进入：

`Settings -> SSH and GPG keys -> New SSH key`

同一把 SSH 公钥通常不能同时绑定到两个 GitHub 账户。

### 2.3 配置 SSH Host 别名

编辑 `~/.ssh/config`：

```sshconfig
Host github-personal
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_personal
    IdentitiesOnly yes
    AddKeysToAgent yes
    UseKeychain yes

Host github-zkcare
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_zkcare
    IdentitiesOnly yes
    AddKeysToAgent yes
    UseKeychain yes
```

`IdentitiesOnly yes` 很重要，它可以防止 SSH 尝试了错误密钥后被 GitHub 拒绝。

设置文件权限：

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/config ~/.ssh/id_ed25519_personal ~/.ssh/id_ed25519_zkcare
chmod 644 ~/.ssh/id_ed25519_personal.pub ~/.ssh/id_ed25519_zkcare.pub
```

### 2.4 验证账户

```bash
ssh -T git@github-personal
ssh -T git@github-zkcare
```

成功时 GitHub 会返回类似信息：

```text
Hi xgame3141! You've successfully authenticated, but GitHub does not provide shell access.
```

重点检查返回的用户名是否符合预期。

## 3. 按项目配置远程仓库

SSH URL 中应使用上面定义的 Host 别名，而不是直接使用 `github.com`。

个人项目：

```bash
git remote set-url origin git@github-personal:personal-user/project.git
```

公司项目：

```bash
git remote set-url origin git@github-zkcare:zkcare/project.git
```

克隆时也使用别名：

```bash
git clone git@github-zkcare:zkcare/project.git
```

查看实际配置：

```bash
git remote -v
```

## 4. 按项目配置 commit 作者

进入项目目录后配置本地身份：

```bash
git config user.name "xgame3141"
git config user.email "YOUR_VERIFIED_EMAIL"
```

如果不希望公开邮箱，可以在 GitHub 的 `Settings -> Emails` 中查看该账户的 `noreply` 邮箱，并将它配置为 `user.email`。

确认当前项目最终生效的配置来源：

```bash
git config --show-origin --get user.name
git config --show-origin --get user.email
```

检查最近一次提交身份：

```bash
git log -1 --format='author: %an <%ae>%ncommitter: %cn <%ce>'
```

如果尚未推送且最近一次提交身份错误，可以修正后执行：

```bash
git commit --amend --reset-author --no-edit
```

已经共享给其他人的历史不要随意重写。

## 5. 按目录自动切换提交身份

如果公司和个人项目存放在不同目录，可以使用 Git 的 `includeIf` 自动加载身份配置。

在 `~/.gitconfig` 中加入：

```gitconfig
[includeIf "gitdir:~/work/personal/"]
    path = ~/.gitconfig-personal

[includeIf "gitdir:~/work/zkcare/"]
    path = ~/.gitconfig-zkcare
```

`~/.gitconfig-personal`：

```gitconfig
[user]
    name = personal-user
    email = personal@example.com
```

`~/.gitconfig-zkcare`：

```gitconfig
[user]
    name = xgame3141
    email = work@example.com
```

注意：

- `gitdir:` 路径建议以 `/` 结尾，表示匹配该目录下的所有仓库。
- macOS 默认文件系统通常不区分大小写，但不要依赖这个行为。
- `includeIf` 只处理 Git 配置；SSH 认证仍由远程 URL 的 Host 别名决定。

## 6. 使用 HTTPS 和 GitHub CLI 切换账户

GitHub CLI 支持保存多个 GitHub 账户：

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth status
gh auth switch --hostname github.com --user xgame3141
gh auth setup-git
```

切换到另一个已登录账户：

```bash
gh auth switch --hostname github.com --user personal-user
```

这种方式需要注意：

- `gh auth switch` 会改变 `github.com` 当前活动账户，通常会影响所有使用 GitHub CLI 凭据助手的 HTTPS 仓库。
- 在多个项目之间频繁操作时，容易忘记切换账户。
- 浏览器已登录某个账户，不代表终端中的 `gh` 或 Git 已使用该账户。
- 对长期并行管理多个账户的场景，SSH Host 别名比 HTTPS 全局切换更可靠。

不要把 Personal Access Token 写入远程 URL、脚本、命令历史或仓库文件。

## 7. 当前 `sts_web_ui` 仓库的推荐配置

为公司账户准备好 `github-zkcare` SSH Host 后，在本仓库执行：

```bash
cd /Users/rgwei/pj/pj_kami/sts_web_ui

git config user.name "xgame3141"
git config user.email "YOUR_ZKCARE_VERIFIED_EMAIL"
git remote set-url origin git@github-zkcare:zkcare/sts_web_ui.git
```

验证配置和权限：

```bash
git config --get user.name
git config --get user.email
git remote -v
ssh -T git@github-zkcare
git fetch origin
```

确认无误后正常推送：

```bash
git push -u origin main
```

## 8. 常见问题排查

### 推送时显示 `Repository not found`

依次检查：

```bash
git remote -v
ssh -T git@github-zkcare
gh auth status
```

常见原因包括：

- 仓库地址或组织名写错。
- 使用了另一个账户的 SSH 密钥或 HTTPS 凭据。
- 当前账户没有私有仓库权限。
- 组织要求 SSO，但当前 Token 或 SSH 密钥尚未获得组织授权。

### SSH 返回了错误的 GitHub 用户名

查看 SSH 实际采用的配置和密钥：

```bash
ssh -G github-zkcare | grep -E '^(hostname|user|identityfile) '
ssh -vT git@github-zkcare
```

重点检查远程 URL 是否使用了 `github-zkcare`，以及配置中是否包含 `IdentitiesOnly yes`。

### commit 显示为错误账户或未关联 GitHub 用户

```bash
git config --show-origin --get-regexp '^user\.'
git log -1 --format='%an <%ae>'
```

确保 `user.email` 是目标 GitHub 账户已验证的邮箱或该账户的 `noreply` 邮箱。

### HTTPS 总是使用错误账户

先确认 GitHub CLI 当前账户：

```bash
gh auth status
gh auth switch --hostname github.com --user TARGET_USER
gh auth setup-git
```

如果项目长期固定使用某个账户，建议将该项目改为 SSH Host 别名方案，避免继续依赖全局 HTTPS 活动账户。

## 9. 日常操作检查清单

在新项目首次推送前检查：

```bash
git config --get user.name
git config --get user.email
git remote -v
git status -sb
```

使用 SSH 时再检查：

```bash
ssh -T git@github-zkcare
```

使用 HTTPS 时再检查：

```bash
gh auth status
```

只要提交身份、远程 Host 别名和认证账户三者一致，多账户项目就能稳定隔离管理。

## 10. 使用脚本切换 `xgame3141` 和 `Zephyrsz`

本仓库提供了切换脚本：

```text
scripts/switch-github-user.sh
```

它针对当前本机的认证方式进行配置：

| 用户 | commit 邮箱 | 推送认证 | 远程 URL |
| --- | --- | --- | --- |
| `xgame3141` | GitHub `noreply` 邮箱 | GitHub CLI | HTTPS |
| `Zephyrsz` | GitHub `noreply` 邮箱 | 默认 GitHub SSH 密钥 | SSH |

切换当前仓库为 `Zephyrsz`：

```bash
/Users/rgwei/pj/pj_kami/sts_web_ui/scripts/switch-github-user.sh Zephyrsz
```

切换当前仓库为 `xgame3141`：

```bash
/Users/rgwei/pj/pj_kami/sts_web_ui/scripts/switch-github-user.sh xgame3141
```

脚本默认执行以下操作：

1. 使用 `git config --local` 设置当前仓库的 `user.name` 和 `user.email`。
2. `xgame3141` 通过 `gh auth switch` 切换 HTTPS 凭据。
3. `Zephyrsz` 验证默认 SSH 密钥返回的 GitHub 用户名。
4. 从现有远程地址提取 `owner/repo`，仅切换 HTTPS 或 SSH 协议。
5. 清除可能覆盖正常远程地址的独立 `pushurl`。
6. 提醒检查最近一次 commit 的作者，但不自动改写提交历史。

只修改 commit 署名，不修改认证和远程地址：

```bash
/Users/rgwei/pj/pj_kami/sts_web_ui/scripts/switch-github-user.sh Zephyrsz --author-only
```

指定其他远程名称：

```bash
/Users/rgwei/pj/pj_kami/sts_web_ui/scripts/switch-github-user.sh xgame3141 --remote upstream
```

查看帮助：

```bash
/Users/rgwei/pj/pj_kami/sts_web_ui/scripts/switch-github-user.sh --help
```

### 为什么修改 `user.name` 后仍然出现 403

下面的命令只修改 commit 署名：

```bash
git config user.name "Zephyrsz"
```

如果 `origin` 仍是 HTTPS，Git 会继续使用 GitHub CLI 或钥匙串中的 `xgame3141` 凭据，因此可能出现：

```text
Permission to Zephyrsz/book_loader.git denied to xgame3141.
```

切换到 `Zephyrsz` 时，脚本会把同一个仓库地址转换为 SSH，例如：

```text
https://github.com/Zephyrsz/book_loader.git
git@github.com:Zephyrsz/book_loader.git
```

SSH 地址会使用已经通过下面命令验证的 `Zephyrsz` 密钥：

```bash
ssh -T git@github.com
```

### 切换后修正最近一次 commit

切换只影响之后创建的 commit。若最近一次 commit 尚未共享，可以执行：

```bash
git commit --amend --reset-author --no-edit
git log -1 --format='%an <%ae>'
```

脚本不会自动运行 `commit --amend`，避免意外改写已经推送的历史。

### 权限仍需由 GitHub 授予

切换身份不会自动获得目标仓库权限。例如，`Zephyrsz` 必须本身是目标仓库的所有者、协作者或组织成员，才能完成推送。脚本会保留现有 `owner/repo`，不会把组织仓库自动改成个人仓库。
