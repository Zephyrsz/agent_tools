# Jupyter Notebook 脚本配置抽取设计

## 背景

`install_jupyter_libraries.sh`、`install_jupyter_notebook.sh` 和
`start_jupyter_notebook.sh` 当前把项目目录、虚拟环境、Notebook 目录、端口和
内核名称等值直接写在脚本中。脚本复制到另一台 Ubuntu 主机后需要修改多个文件，
容易产生路径和参数不一致。

## 目标

- 在三个脚本同目录新增一个 `env.cfg`，集中维护部署参数。
- 脚本通过自身目录定位 `env.cfg`，不依赖调用时的当前工作目录。
- 复制整个目录到另一台 Ubuntu 主机后，只需修改 `env.cfg` 即可部署。
- 保持现有命令行用法和默认行为兼容。

## 方案

`env.cfg` 使用 Bash 配置语法，由脚本通过 `source` 加载。配置由部署者维护，允许
使用引号和变量展开，例如虚拟环境和数据目录可以引用 `PROJECT_DIR`。配置文件示例：

```bash
PROJECT_DIR="/home/rgwei/pj_juypter"
VENV_DIR="${PROJECT_DIR}/ju_venv"
NOTEBOOK_DIR="${PROJECT_DIR}/data"
REQ_FILE="${PROJECT_DIR}/requirements-jupyter.txt"
HOST="0.0.0.0"
PORT="21092"
KERNEL_NAME="ju_venv"
KERNEL_DISPLAY_NAME="Python (ju_venv)"
PID_FILE="${PROJECT_DIR}/jupyter_notebook.pid"
LOG_FILE="${PROJECT_DIR}/jupyter_notebook.log"
```

脚本只读取上述配置字段，并在加载后校验关键字段非空。缺少 `env.cfg` 或字段为空
时，脚本向标准错误输出带 `[config] ERROR:` 前缀的错误并退出，不继续执行安装或启动。

### 配置加载和优先级

每个脚本先计算：

```bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
CONFIG_FILE="${SCRIPT_DIR}/env.cfg"
```

然后加载并校验 `${CONFIG_FILE}`。三个脚本中不再写死部署根目录、虚拟环境、Notebook
目录、端口、PID/日志路径或内核名称。

`install_jupyter_libraries.sh` 保留现有接口：

```text
install_jupyter_libraries.sh [VENV] [REQ_FILE]
```

传入的位置参数优先于 `env.cfg`；没有传参时使用配置值。这样既支持复制部署，也不破坏
现有的临时路径覆盖方式。其他两个脚本保持现有接口：

- `install_jupyter_notebook.sh [install-only]`
- `start_jupyter_notebook.sh [start|stop|restart|status]`

## 脚本职责变化

### `install_jupyter_libraries.sh`

- 从同目录加载 `env.cfg`。
- 使用配置的 `VENV_DIR` 和 `REQ_FILE`，位置参数可覆盖它们。
- 保留当前 Jupyter 基础包和额外 requirements 的安装逻辑。

### `install_jupyter_notebook.sh`

- 从同目录加载 `env.cfg`。
- 使用配置的 `VENV_DIR` 创建或检查虚拟环境，使用 `NOTEBOOK_DIR` 创建数据目录。
- 从同目录调用 `install_jupyter_libraries.sh`，避免依赖项目根目录中的固定路径。
- 保留 `install-only` 行为；默认仍在安装后前台启动 Notebook。
- 使用配置的 Host、端口和内核参数启动 Notebook。

### `start_jupyter_notebook.sh`

- 从同目录加载 `env.cfg`。
- 使用配置的虚拟环境、Notebook 目录、Host、端口、PID 文件、日志文件和内核参数。
- 保留 `start`、`stop`、`restart`、`status` 生命周期命令和现有 PID 文件行为。
- 启动时仍调用同目录的库安装脚本，并确保内核已注册。

## 错误处理

- `env.cfg` 不存在：立即失败并打印配置文件的绝对路径。
- 关键配置为空：立即失败并指出字段名。
- 虚拟环境不存在或解释器不可执行：沿用现有错误并提示先创建/安装环境。
- requirements 文件不存在：沿用现有行为，跳过额外依赖安装；基础 Jupyter 包仍安装。
- 启动端口、PID 文件、日志文件和目录的行为保持现状，不引入新的后台管理机制。

## 测试和验证

- 对三个脚本运行 `bash -n`，验证 Shell 语法。
- 使用临时 `env.cfg` 验证：脚本能从非当前工作目录加载配置，配置中的路径和端口会传递
  到对应命令。
- 验证 `install_jupyter_libraries.sh` 的位置参数仍可覆盖配置。
- 验证缺少配置文件和缺少必填字段时返回非零状态并打印可读错误。
- 在不实际安装 Jupyter 的前提下，使用命令替身或静态检查覆盖配置加载和参数传递路径。

## 不在本次范围内

- 不改变 Jupyter、JupyterLab 或 ipykernel 的安装版本策略。
- 不增加 systemd 服务、认证、TLS 或反向代理配置。
- 不修改其他目录中的 Notebook 工具。
