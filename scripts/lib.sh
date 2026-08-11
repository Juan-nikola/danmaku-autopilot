#!/usr/bin/env bash

# Shared helpers for host-side operations. This file intentionally never mounts
# or talks to the Docker socket; all Docker actions go through Compose.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
COMPOSE_FILE="${COMPOSE_FILE:-${PROJECT_ROOT}/compose.yaml}"
ENV_FILE="${ENV_FILE:-${PROJECT_ROOT}/.env}"
BACKUP_DIR="${BACKUP_DIR:-${PROJECT_ROOT}/state/backups}"
LOCK_DIR="${LOCK_DIR:-${PROJECT_ROOT}/state/locks}"

log() { printf '[danmu] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

require_cmd() {
  have "$1" || die "required command not found: $1"
}

load_env() {
  [[ -f "$ENV_FILE" ]] || die "missing ${ENV_FILE}; run scripts/bootstrap.sh first"
  # shellcheck disable=SC1090
  set -a
  source "$ENV_FILE"
  set +a
}

compose() {
  require_cmd docker
  sync_image_env
  docker compose --project-directory "$PROJECT_ROOT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

sync_image_env() {
  local lock="${PROJECT_ROOT}/deploy/images.lock"
  [[ -f "$lock" ]] || die "missing ${lock}; run scripts/bootstrap.sh first"
  export MISAKA_IMAGE="$(awk -F= '$1 == "MISAKA_IMAGE" {print substr($0, index($0, "=") + 1); exit}' "$lock")"
  export DANMU_API_IMAGE="$(awk -F= '$1 == "DANMU_API_IMAGE" {print substr($0, index($0, "=") + 1); exit}' "$lock")"
  export MYSQL_IMAGE="$(awk -F= '$1 == "MYSQL_IMAGE" {print substr($0, index($0, "=") + 1); exit}' "$lock")"
  [[ "$MISAKA_IMAGE" =~ @sha256:[0-9a-fA-F]{64}$ ]] || die "MISAKA_IMAGE is not digest-pinned"
  [[ "$DANMU_API_IMAGE" =~ @sha256:[0-9a-fA-F]{64}$ ]] || die "DANMU_API_IMAGE is not digest-pinned"
  [[ "$MYSQL_IMAGE" == mysql:8.1.0-oracle ]] || die "MYSQL_IMAGE must remain mysql:8.1.0-oracle"
}

ensure_dir() {
  local path="$1"
  mkdir -p -- "$path"
}

with_lock() {
  local name="$1"
  shift
  ensure_dir "$LOCK_DIR"
  local lock_file="${LOCK_DIR}/${name}.lock"
  if have flock; then
    flock -n "$lock_file" "$@" || die "another ${name} operation is already running"
  else
    local lock_dir="${lock_file}.d"
    if ! mkdir -- "$lock_dir" 2>/dev/null; then
      die "another ${name} operation is already running (install flock for robust locking)"
    fi
    trap 'rmdir -- "${lock_dir}" 2>/dev/null || true' RETURN
    "$@"
  fi
}

random_secret() {
  require_cmd openssl
  openssl rand -hex 32
}

write_secret_once() {
  local file="$1"
  local value="$2"
  if [[ ! -e "$file" ]]; then
    (umask 077; printf '%s\n' "$value" >"$file")
  fi
  chmod 600 "$file"
}

safe_backup_path() {
  local candidate="$1"
  local base candidate_abs
  base="$(cd -- "$BACKUP_DIR" 2>/dev/null && pwd -P)" || die "backup directory does not exist: $BACKUP_DIR"
  candidate_abs="$(cd -- "$(dirname -- "$candidate")" 2>/dev/null && pwd -P)/$(basename -- "$candidate")" \
    || die "backup path does not exist: $candidate"
  case "$candidate_abs" in
    "$base"/*) printf '%s\n' "$candidate_abs" ;;
    *) die "refusing path outside backup directory" ;;
  esac
}

redact_url() {
  # Keep host/path shape but never print query strings or token-like path parts.
  sed -E 's#(https?://[^/?]+)[^ ]*#\1/[REDACTED]#g; s#(token|key|secret|password)[^/ ]*#\1-[REDACTED]#gi'
}
