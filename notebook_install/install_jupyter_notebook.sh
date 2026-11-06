#!/usr/bin/env bash
set -euo pipefail

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

VENV="${VENV_DIR:-}"
NOTEBOOK_DIR="${NOTEBOOK_DIR:-}"
HOST="${HOST:-}"
PORT="${PORT:-}"
KERNEL_NAME="${KERNEL_NAME:-}"
KERNEL_DISPLAY_NAME="${KERNEL_DISPLAY_NAME:-}"
INSTALL_LIB_SCRIPT="${SCRIPT_DIR}/install_jupyter_libraries.sh"

for config_name in VENV_DIR NOTEBOOK_DIR HOST PORT KERNEL_NAME KERNEL_DISPLAY_NAME; do
  if [[ -z "${!config_name:-}" ]]; then
    echo "[config] ERROR: ${config_name} is empty" >&2
    exit 1
  fi
done

if [[ ! -x "${VENV}/bin/python" ]]; then
  echo "Creating Python venv in ${VENV} ..."
  python3 -m venv "${VENV}"
fi

if [[ ! -x "${VENV}/bin/python" ]]; then
  echo "Missing Python interpreter in ${VENV}" >&2
  exit 1
fi

mkdir -p "${NOTEBOOK_DIR}"

if [[ -x "${INSTALL_LIB_SCRIPT}" ]]; then
  "${INSTALL_LIB_SCRIPT}" "${VENV}"
else
  "${VENV}/bin/python" -m pip install --upgrade pip setuptools wheel notebook ipykernel jupyterlab
fi

"${VENV}/bin/python" -m ipykernel install --user \
  --name "${KERNEL_NAME}" \
  --display-name "${KERNEL_DISPLAY_NAME}"

if [[ "${1:-start}" == "install-only" ]]; then
  exit 0
fi

export VIRTUAL_ENV="${VENV}"
export PATH="${VENV}/bin:${PATH}"

exec "${VENV}/bin/python" -m notebook \
  --notebook-dir="${NOTEBOOK_DIR}" \
  --ip="${HOST}" \
  --port="${PORT}" \
  --no-browser \
  --MappingKernelManager.default_kernel_name="${KERNEL_NAME}"
