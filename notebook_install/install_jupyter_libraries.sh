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

if [[ ! -x "${VENV}/bin/python" ]]; then
  echo "Missing Python interpreter in ${VENV}" >&2
  echo "Create the venv first: python3 -m venv ${VENV}" >&2
  exit 1
fi

echo "Installing base Jupyter libraries into ${VENV} ..."
"${VENV}/bin/python" -m pip install --upgrade \
  pip \
  setuptools \
  wheel \
  notebook \
  jupyterlab \
  ipykernel

if [[ -f "${REQ_FILE}" ]]; then
  echo "Installing extra libraries from ${REQ_FILE} ..."
  "${VENV}/bin/python" -m pip install -r "${REQ_FILE}"
fi

echo "Library installation completed for ${VENV}."
