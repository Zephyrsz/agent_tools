#!/usr/bin/env bash

set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  extract_media.sh [--force] <input.mp4> [output_dir]

Outputs:
  <input-stem>.video.mp4  Video stream only, copied without re-encoding.
  <input-stem>.m4a        Audio stream only, copied without re-encoding.

By default output_dir is the directory containing this script. Existing output
files are preserved unless --force is supplied.
EOF
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

force=0
while (($# > 0)); do
  case "$1" in
    -f|--force)
      force=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      usage >&2
      die "Unknown option: $1"
      ;;
    *)
      break
      ;;
  esac
done

if (($# < 1 || $# > 2)); then
  usage >&2
  exit 64
fi

input=$1
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
output_dir=${2:-$script_dir}

[[ -f "$input" ]] || die "Input file does not exist: $input"
command -v ffmpeg >/dev/null 2>&1 || die "ffmpeg is not installed or not on PATH"
command -v ffprobe >/dev/null 2>&1 || die "ffprobe is not installed or not on PATH"

mkdir -p "$output_dir"
output_dir="$(cd "$output_dir" && pwd -P)"

input_name="$(basename "$input")"
stem="${input_name%.*}"
[[ -n "$stem" && "$stem" != "$input_name" ]] || stem="$input_name"

video_output="$output_dir/${stem}.video.mp4"
audio_output="$output_dir/${stem}.m4a"

if ((force == 0)) && { [[ -e "$video_output" ]] || [[ -e "$audio_output" ]]; }; then
  die "Output already exists; use --force to replace: $video_output or $audio_output"
fi

if ! video_stream="$(ffprobe -v error -select_streams v:0 \
  -show_entries stream=index -of csv=p=0 "$input" 2>/dev/null)"; then
  die "Could not read the input media: $input"
fi
[[ -n "$video_stream" ]] || die "Input has no video stream: $input"

if ! audio_stream="$(ffprobe -v error -select_streams a:0 \
  -show_entries stream=index -of csv=p=0 "$input" 2>/dev/null)"; then
  die "Could not read the input media: $input"
fi
[[ -n "$audio_stream" ]] || die "Input has no audio stream: $input"

temp_dir="$(mktemp -d "$output_dir/.${stem}.extract.XXXXXX")"
cleanup() {
  rm -rf "$temp_dir"
}
trap cleanup EXIT

temp_video="$temp_dir/${stem}.video.mp4"
temp_audio="$temp_dir/${stem}.m4a"
overwrite_flag=(-n)
if ((force == 1)); then
  overwrite_flag=(-y)
fi

printf 'Input: %s\n' "$input"
printf 'Writing video: %s\n' "$video_output"
ffmpeg -hide_banner "${overwrite_flag[@]}" -i "$input" \
  -map 0:v:0 -an -c:v copy -movflags +faststart "$temp_video"

printf 'Writing audio: %s\n' "$audio_output"
ffmpeg -hide_banner "${overwrite_flag[@]}" -i "$input" \
  -map 0:a:0 -vn -c:a copy -movflags +faststart "$temp_audio"

mv -f "$temp_video" "$video_output"
mv -f "$temp_audio" "$audio_output"
printf 'Done.\n'
