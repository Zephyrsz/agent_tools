# Jupyter Notebook Configurable Scripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the shared Jupyter deployment paths and runtime settings into a same-directory `env.cfg` used by the three Notebook scripts.

**Architecture:** Each script computes its own `SCRIPT_DIR`, validates and sources `SCRIPT_DIR/env.cfg`, then uses the resulting variables. The library installer keeps its two positional overrides; the Notebook installer and lifecycle script keep their existing command interfaces and derive the helper-script path from `SCRIPT_DIR`.

**Tech Stack:** Bash 4+, standard POSIX utilities, Python virtual environments, Jupyter Notebook/JupyterLab, ipykernel.

---

### Task 1: Add the shared deployment configuration

**Files:**
- Create: `/Users/rgwei/pj/pj_agent/agent_tools/notebook_install/env.cfg`

- [ ] **Step 1: Add the configuration template with the current defaults**

```bash
# Shared Jupyter Notebook deployment configuration.
# This file is sourced by the scripts in this directory.
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

- [ ] **Step 2: Verify the template has the required keys and no syntax errors**

Run:

```bash
bash -n /Users/rgwei/pj/pj_agent/agent_tools/notebook_install/env.cfg
```

Expected: exit status `0`.

### Task 2: Make the library installer consume `env.cfg`

**Files:**
- Modify: `/Users/rgwei/pj/pj_agent/agent_tools/notebook_install/install_jupyter_libraries.sh`

- [ ] **Step 1: Replace hard-coded defaults with same-directory config loading**

At the top of the script, after `set -euo pipefail`, compute `SCRIPT_DIR` and `CONFIG_FILE`; fail with `[config] ERROR:` if the file is missing or has invalid Bash syntax; source it; then set the effective values with CLI precedence:

```bash
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
CONFIG_FILE="${SCRIPT_DIR}/env.cfg"

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "[config] ERROR: missing config file: ${CONFIG_FILE}" >&2
  exit 1
fi
if ! bash -n "${CONFIG_FILE}"; then
  echo "[config] ERROR: invalid config syntax: ${CONFIG_FILE}" >&2
  exit 1
fi
# shellcheck source=/dev/null
. "${CONFIG_FILE}"

VENV="${1:-${VENV_DIR:-}}"
REQ_FILE="${2:-${REQ_FILE:-}}"

if [[ -z "${VENV}" ]]; then
  echo "[config] ERROR: VENV_DIR is empty and no VENV argument was supplied" >&2
  exit 1
fi
if [[ -z "${REQ_FILE}" ]]; then
  echo "[config] ERROR: REQ_FILE is empty and no requirements argument was supplied" >&2
  exit 1
fi
```

Keep the existing virtual-environment check and pip installation commands unchanged after this block.

- [ ] **Step 2: Confirm positional overrides remain effective**

Run the script with a fake executable interpreter and a temporary requirements path, or inspect the resulting command arguments with a command stub. Expected: argument 1 replaces `VENV_DIR` and argument 2 replaces `REQ_FILE`.

### Task 3: Make the one-shot Notebook installer consume the shared config

**Files:**
- Modify: `/Users/rgwei/pj/pj_agent/agent_tools/notebook_install/install_jupyter_notebook.sh`

- [ ] **Step 1: Load and validate config-derived runtime values**

Replace the hard-coded variable block with `SCRIPT_DIR`, `CONFIG_FILE`, config validation/sourcing, and these assignments:

```bash
VENV="${VENV_DIR:-}"
NOTEBOOK_DIR="${NOTEBOOK_DIR:-}"
HOST="${HOST:-}"
PORT="${PORT:-}"
KERNEL_NAME="${KERNEL_NAME:-}"
KERNEL_DISPLAY_NAME="${KERNEL_DISPLAY_NAME:-}"
INSTALL_LIB_SCRIPT="${SCRIPT_DIR}/install_jupyter_libraries.sh"
```

Validate each effective value and fail with `[config] ERROR: <name> is empty` before creating directories or environments.

- [ ] **Step 2: Preserve command behavior while removing the fixed helper path**

Keep `install-only` and default foreground startup unchanged. Invoke `${INSTALL_LIB_SCRIPT}` with `${VENV}` when it is executable; the helper then reads the same `env.cfg` for `REQ_FILE`. Pass configured `NOTEBOOK_DIR`, `HOST`, `PORT`, and kernel values to the final Notebook command.

### Task 4: Make the lifecycle script consume the shared config

**Files:**
- Modify: `/Users/rgwei/pj/pj_agent/agent_tools/notebook_install/start_jupyter_notebook.sh`

- [ ] **Step 1: Replace fixed runtime paths and port with config values**

Load and validate the same config keys as Task 3, plus `PID_FILE` and `LOG_FILE`; set `INSTALL_LIB_SCRIPT="${SCRIPT_DIR}/install_jupyter_libraries.sh"`.

- [ ] **Step 2: Keep lifecycle commands and use configured paths**

Leave `start`, `stop`, `restart`, and `status` dispatch intact. Use configured `NOTEBOOK_DIR`, `PID_FILE`, and `LOG_FILE`; create the Notebook directory and the parent directories of the PID/log files before startup. Keep the existing kernel registration, `nohup`, PID writing, and stop behavior.

### Task 5: Verify integration and preserve unrelated work

**Files:**
- Test: `/Users/rgwei/pj/pj_agent/agent_tools/notebook_install/env.cfg`
- Test: `/Users/rgwei/pj/pj_agent/agent_tools/notebook_install/install_jupyter_libraries.sh`
- Test: `/Users/rgwei/pj/pj_agent/agent_tools/notebook_install/install_jupyter_notebook.sh`
- Test: `/Users/rgwei/pj/pj_agent/agent_tools/notebook_install/start_jupyter_notebook.sh`

- [ ] **Step 1: Run Bash syntax checks**

```bash
for script in /Users/rgwei/pj/pj_agent/agent_tools/notebook_install/env.cfg \
  /Users/rgwei/pj/pj_agent/agent_tools/notebook_install/install_jupyter_libraries.sh \
  /Users/rgwei/pj/pj_agent/agent_tools/notebook_install/install_jupyter_notebook.sh \
  /Users/rgwei/pj/pj_agent/agent_tools/notebook_install/start_jupyter_notebook.sh; do
  bash -n "${script}"
done
```

Expected: all commands exit `0`.

- [ ] **Step 2: Run static configuration contract checks**

Confirm all three scripts contain `SCRIPT_DIR`, `CONFIG_FILE`, and `. "${CONFIG_FILE}"`; confirm the old hard-coded `/home/rgwei/pj_juypter` and `21092` literals are present only in `env.cfg`; confirm the library installer still uses both positional arguments.

- [ ] **Step 3: Exercise missing-config failure without installing packages**

Copy one script to a temporary directory without `env.cfg` and run it. Expected: non-zero exit and stderr containing `[config] ERROR: missing config file:`.

- [ ] **Step 4: Review the final diff and status**

```bash
git -C /Users/rgwei/pj/pj_agent/agent_tools diff --check
git -C /Users/rgwei/pj/pj_agent/agent_tools diff -- notebook_install
git -C /Users/rgwei/pj/pj_agent/agent_tools status --short
```

Expected: only the intended four Notebook files are staged/modified by this work; pre-existing `.DS_Store` and unrelated untracked directories remain untouched.

- [ ] **Step 5: Commit the implementation**

```bash
git -C /Users/rgwei/pj/pj_agent/agent_tools add \
  notebook_install/env.cfg \
  notebook_install/install_jupyter_libraries.sh \
  notebook_install/install_jupyter_notebook.sh \
  notebook_install/start_jupyter_notebook.sh
git -C /Users/rgwei/pj/pj_agent/agent_tools commit -m "feat: configure jupyter notebook scripts"
```
