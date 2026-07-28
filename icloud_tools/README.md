# macOS iCloud Drive 文件工具

`icloud_drive.py` 通过 macOS 本地的 iCloud Drive 目录读取、上传和下载文件，不调用私有 API，也不需要额外的 Python 依赖。

默认 iCloud Drive 路径：

```text
~/Library/Mobile Documents/com~apple~CloudDocs
```

## 快速开始

在仓库根目录运行：

```bash
# 检查路径和访问权限
/Users/rgwei/anaconda3/bin/python icloud_tools/icloud_drive.py status

# 查看 iCloud Drive 根目录
/Users/rgwei/anaconda3/bin/python icloud_tools/icloud_drive.py list

# 递归查看 Documents 目录
/Users/rgwei/anaconda3/bin/python icloud_tools/icloud_drive.py list Documents --recursive

# 读取 UTF-8 文本文件
/Users/rgwei/anaconda3/bin/python icloud_tools/icloud_drive.py read "Documents/notes.txt"

# 把本地文件复制到 iCloud Drive 根目录
/Users/rgwei/anaconda3/bin/python icloud_tools/icloud_drive.py upload ./report.pdf

# 复制到 iCloud Drive 的指定相对路径（自动创建父目录）
/Users/rgwei/anaconda3/bin/python icloud_tools/icloud_drive.py upload \
  ./report.pdf "Work/Reports/report.pdf"

# 把整个本地目录复制到 iCloud Drive
/Users/rgwei/anaconda3/bin/python icloud_tools/icloud_drive.py upload \
  ./my-project "Backups/my-project"

# 从 iCloud Drive 下载到当前目录
/Users/rgwei/anaconda3/bin/python icloud_tools/icloud_drive.py download \
  "Work/Reports/report.pdf"

# 下载到指定本地路径
/Users/rgwei/anaconda3/bin/python icloud_tools/icloud_drive.py download \
  "Work/Reports/report.pdf" ./downloads/report.pdf
```

默认不会覆盖已经存在的文件或目录。确认需要覆盖或合并目录时，添加 `--overwrite`：

```bash
/Users/rgwei/anaconda3/bin/python icloud_tools/icloud_drive.py upload \
  ./report.pdf "Work/report.pdf" --overwrite
```

所有 iCloud 参数都是相对于 iCloud Drive 根目录的路径。脚本会拒绝绝对路径、`../` 越界以及通过符号链接跳出 iCloud Drive 的路径。

## macOS 权限

如果出现 `Operation not permitted` 或脚本报告 macOS 拒绝访问：

1. 打开“系统设置” > “隐私与安全性”。
2. 在“文件与文件夹”中允许当前终端访问 iCloud Drive。
3. 如果仍被拒绝，在“完全磁盘访问权限”中启用 Terminal、iTerm、Warp 或实际运行 Python 的应用。
4. 完全退出并重新打开终端后，再运行 `status`。

文件读取会触发 macOS 按需下载尚未保存在本地的 iCloud 文件，因此首次读取可能需要等待网络下载。复制到本地 iCloud Drive 后，系统会异步上传到云端；脚本成功仅表示本地复制完成，不表示云端同步已经完成。

## 自定义路径和测试

可以用全局 `--root` 参数或 `ICLOUD_DRIVE_PATH` 环境变量覆盖根目录：

```bash
/Users/rgwei/anaconda3/bin/python icloud_tools/icloud_drive.py \
  --root /tmp/test-cloud status
ICLOUD_DRIVE_PATH=/tmp/test-cloud \
  /Users/rgwei/anaconda3/bin/python icloud_tools/icloud_drive.py list
```

运行测试：

```bash
/Users/rgwei/anaconda3/bin/python -m pip install \
  -r icloud_tools/requirement.txt
/Users/rgwei/anaconda3/bin/python -m unittest discover \
  -s icloud_tools/tests -v
```
