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
PID_FILE="${PID_FILE:-}"
LOG_FILE="${LOG_FILE:-}"
KERNEL_NAME="${KERNEL_NAME:-}"
KERNEL_DISPLAY_NAME="${KERNEL_DISPLAY_NAME:-}"
INSTALL_LIB_SCRIPT="${SCRIPT_DIR}/install_jupyter_libraries.sh"

for config_name in VENV_DIR NOTEBOOK_DIR HOST PORT PID_FILE LOG_FILE KERNEL_NAME KERNEL_DISPLAY_NAME; do
  if [[ -z "${!config_name:-}" ]]; then
    echo "[config] ERROR: ${config_name} is empty" >&2
    exit 1
  fi
done

if [[ ! -x "${VENV}/bin/python" ]]; then
	echo "Missing Python interpreter in ${VENV}" >&2
	echo "Create the venv first: python3 -m venv ${VENV}" >&2
	exit 1
fi

	mkdir -p "${NOTEBOOK_DIR}" "$(dirname "${PID_FILE}")" "$(dirname "${LOG_FILE}")"

ensure_kernel() {
	"${VENV}/bin/python" -m pip install --quiet --disable-pip-version-check ipykernel >/dev/null
	"${VENV}/bin/python" -m ipykernel install --user \
		--name "${KERNEL_NAME}" \
		--display-name "${KERNEL_DISPLAY_NAME}" \
		>/dev/null
}

is_running() {
	if [[ ! -f "${PID_FILE}" ]]; then
		return 1
	fi

	local pid
	pid="$(cat "${PID_FILE}")"

	if [[ -z "${pid}" ]]; then
		return 1
	fi

	kill -0 "${pid}" 2>/dev/null
}

start_notebook() {
	if [[ -x "${INSTALL_LIB_SCRIPT}" ]]; then
		"${INSTALL_LIB_SCRIPT}" "${VENV}"
	fi

	ensure_kernel

	if is_running; then
		echo "Jupyter Notebook is already running (PID $(cat "${PID_FILE}"))."
		return 0
	fi

	export VIRTUAL_ENV="${VENV}"
	export PATH="${VENV}/bin:${PATH}"

	echo "Starting Jupyter Notebook on ${HOST}:${PORT} ..."
	nohup "${VENV}/bin/python" -m notebook \
		--notebook-dir="${NOTEBOOK_DIR}" \
		--ip="${HOST}" \
		--port="${PORT}" \
		--no-browser \
		--MappingKernelManager.default_kernel_name="${KERNEL_NAME}" \
		>"${LOG_FILE}" 2>&1 &

	echo $! > "${PID_FILE}"
	echo "Started (PID $(cat "${PID_FILE}")). Logs: ${LOG_FILE}"
}

stop_notebook() {
	if ! is_running; then
		rm -f "${PID_FILE}"
		echo "Jupyter Notebook is not running."
		return 0
	fi

	local pid
	pid="$(cat "${PID_FILE}")"

	echo "Stopping Jupyter Notebook (PID ${pid}) ..."
	kill "${pid}" 2>/dev/null || true
	rm -f "${PID_FILE}"
	echo "Stopped."
}

status_notebook() {
	if is_running; then
		echo "Jupyter Notebook is running (PID $(cat "${PID_FILE}"))."
	else
		echo "Jupyter Notebook is not running."
	fi
}

case "${1:-start}" in
	start)
		start_notebook
		;;
	stop)
		stop_notebook
		;;
	restart)
		stop_notebook
		start_notebook
		;;
	status)
		status_notebook
		;;
	*)
		echo "Usage: $0 {start|stop|restart|status}" >&2
		exit 1
		;;
esac
