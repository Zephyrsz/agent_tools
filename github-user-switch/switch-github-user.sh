#!/usr/bin/env bash

set -euo pipefail

usage() {
    cat <<'EOF'
Usage:
  switch-github-user.sh <xgame3141|Zephyrsz> [options]

Options:
  --author-only     Only change this repository's commit author.
  --remote <name>  Remote to update (default: origin).
  -h, --help       Show this help.

Examples:
  switch-github-user.sh Zephyrsz
  switch-github-user.sh xgame3141
  switch-github-user.sh Zephyrsz --author-only
  switch-github-user.sh xgame3141 --remote upstream
EOF
}

die() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

github_repo_path() {
    local url="$1"
    local path

    case "$url" in
        https://github.com/*)
            path="${url#https://github.com/}"
            ;;
        http://github.com/*)
            path="${url#http://github.com/}"
            ;;
        git@github.com:*)
            path="${url#git@github.com:}"
            ;;
        ssh://git@github.com/*)
            path="${url#ssh://git@github.com/}"
            ;;
        *)
            return 1
            ;;
    esac

    path="${path%/}"
    path="${path%.git}"

    case "$path" in
        */*) printf '%s\n' "$path" ;;
        *) return 1 ;;
    esac
}

TARGET_USER="${1:-}"
if [[ -z "$TARGET_USER" ]]; then
    usage
    exit 1
fi
if [[ "$TARGET_USER" == "-h" || "$TARGET_USER" == "--help" ]]; then
    usage
    exit 0
fi
shift

AUTHOR_ONLY=false
REMOTE_NAME="origin"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --author-only)
            AUTHOR_ONLY=true
            shift
            ;;
        --remote)
            [[ $# -ge 2 ]] || die "--remote requires a remote name"
            REMOTE_NAME="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

case "$TARGET_USER" in
    xgame3141)
        TARGET_EMAIL="279920948+xgame3141@users.noreply.github.com"
        AUTH_MODE="https"
        ;;
    Zephyrsz)
        TARGET_EMAIL="22188415+Zephyrsz@users.noreply.github.com"
        AUTH_MODE="ssh"
        ;;
    *)
        die "supported users are xgame3141 and Zephyrsz"
        ;;
esac

command_exists git || die "git is not installed"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || \
    die "run this script inside the Git repository you want to switch"

git config --local user.name "$TARGET_USER"
git config --local user.email "$TARGET_EMAIL"

printf 'Commit author switched for this repository:\n'
printf '  name:  %s\n' "$(git config --local --get user.name)"
printf '  email: %s\n' "$(git config --local --get user.email)"

if [[ "$AUTHOR_ONLY" == true ]]; then
    printf 'Authentication and remote URL were not changed (--author-only).\n'
    exit 0
fi

if [[ "$AUTH_MODE" == "https" ]]; then
    command_exists gh || \
        die "GitHub CLI is required for xgame3141; install it with: brew install gh"

    if ! gh auth switch --hostname github.com --user xgame3141 >/dev/null 2>&1; then
        die "xgame3141 is not stored in gh; run: gh auth login --hostname github.com --git-protocol https --web"
    fi
    gh auth setup-git
    printf 'GitHub CLI authentication switched to xgame3141.\n'
else
    ssh_output="$(ssh -T -o BatchMode=yes -o ConnectTimeout=10 git@github.com 2>&1 || true)"
    if [[ "$ssh_output" != *"Hi Zephyrsz!"* ]]; then
        printf '%s\n' "$ssh_output" >&2
        die "the default GitHub SSH key is not authenticated as Zephyrsz"
    fi
    printf 'SSH authentication verified as Zephyrsz.\n'
fi

if ! git remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
    printf 'Remote %s does not exist; authentication changed, but no URL was updated.\n' "$REMOTE_NAME"
    exit 0
fi

CURRENT_URL="$(git remote get-url "$REMOTE_NAME")"
if ! REPO_PATH="$(github_repo_path "$CURRENT_URL")"; then
    die "cannot safely convert non-GitHub remote URL: $CURRENT_URL"
fi

# A separately configured pushurl overrides the normal remote URL.
git config --unset-all "remote.${REMOTE_NAME}.pushurl" >/dev/null 2>&1 || true

if [[ "$AUTH_MODE" == "https" ]]; then
    NEW_URL="https://github.com/${REPO_PATH}.git"
else
    NEW_URL="git@github.com:${REPO_PATH}.git"
fi

git remote set-url "$REMOTE_NAME" "$NEW_URL"

printf 'Remote updated without changing the repository owner or name:\n'
printf '  %s -> %s\n' "$REMOTE_NAME" "$(git remote get-url --push "$REMOTE_NAME")"
printf '\nCurrent state:\n'
printf '  author: %s <%s>\n' \
    "$(git config --local --get user.name)" \
    "$(git config --local --get user.email)"

if git rev-parse --verify HEAD >/dev/null 2>&1; then
    last_author="$(git log -1 --format='%an <%ae>')"
    printf '  latest commit author: %s\n' "$last_author"
    if [[ "$last_author" != "${TARGET_USER} <${TARGET_EMAIL}>" ]]; then
        printf '\nThe latest commit was created with another identity.\n'
        printf 'If it has not been shared, update it with:\n'
        printf '  git commit --amend --reset-author --no-edit\n'
    fi
fi

printf '\nBefore pushing, confirm that %s has access to %s.\n' \
    "$TARGET_USER" "$REPO_PATH"
