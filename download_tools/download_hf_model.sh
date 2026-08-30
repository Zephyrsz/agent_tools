#!/usr/bin/env bash
set -euo pipefail

if (( $# < 2 )); then
  echo "Usage: $0 <hf_model_id> <output_dir> [download options...]" >&2
  echo "Example: $0 Qwen/Qwen3-8B /data/models/Qwen3-8B" >&2
  exit 2
fi

model_id=$1
output_dir=$2
shift 2

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python_bin=${PYTHON:-python3}

exec "$python_bin" "$script_dir/download_hf_model.py" \
  "$model_id" \
  --local-dir "$output_dir" \
  "$@"
