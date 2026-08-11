#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib.sh"

mode=""
engine="misaka"
while (($#)); do
  case "$1" in
    --check|--apply) [[ -z "$mode" ]] || die "choose only --check or --apply"; mode="${1#--}" ;;
    --engine) (($# >= 2)) || die "--engine requires misaka or danmu-api"; engine="$2"; shift ;;
    -h|--help) printf 'Usage: scripts/update.sh --check|--apply [--engine misaka|danmu-api]\n'; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done
[[ -n "$mode" ]] || die "update requires --check or --apply"
[[ "$engine" == misaka || "$engine" == danmu-api ]] || die "invalid update engine"
load_env
[[ -f "$PROJECT_ROOT/deploy/images.lock" ]] || die "deploy/images.lock is missing; run bootstrap first"

printf 'Locked images:\n'
grep -E '^(MISAKA_IMAGE|DANMU_API_IMAGE|MYSQL_IMAGE)=' "$PROJECT_ROOT/deploy/images.lock" || true
if ! grep -Eq 'sha256:[0-9a-fA-F]{64}' "$PROJECT_ROOT/deploy/images.lock"; then
  log "warning: one or more application images are not digest-pinned; resolve them before apply"
fi
if [[ "$mode" == check ]]; then
  log "check mode: no backup, pull, restart, or lock-file changes were made"
  exit 0
fi

apply_update() {
  local old_lock backup_id service
  old_lock="${PROJECT_ROOT}/state/old-images.lock"
  cp -p -- "$PROJECT_ROOT/deploy/images.lock" "$old_lock"
  # A pre-update backup must complete before Compose recreates anything.
  backup_id="$("${SCRIPT_DIR}/backup.sh" --reason pre-update | tail -n 1)"
  service="$engine"
  local failed=0
  if ! compose pull "$service"; then
    failed=1
  fi
  if (( ! failed )) && ! compose up -d --no-deps "$service"; then
    failed=1
  fi

  if ! "${SCRIPT_DIR}/healthcheck.sh"; then
    failed=1
  fi
  if ((failed)); then
    log "update failed; writing old images.lock and restoring pre-update backup"
    cp -p -- "$old_lock" "$PROJECT_ROOT/deploy/images.lock"
    # The literal command is intentionally kept here for audit/review: restore
    # always verifies and creates a safety backup before applying.
    "${SCRIPT_DIR}/restore.sh" "$backup_id" --apply || log "warning: automatic data restore needs manual attention"
    compose up -d --no-deps "$service"
    "${SCRIPT_DIR}/healthcheck.sh"
    return 1
  fi
  ensure_dir "$PROJECT_ROOT/state/versions"
  printf '%s\n' "$backup_id" >"${PROJECT_ROOT}/state/versions/$(date -u +%Y%m%dT%H%M%SZ)-${engine}.successful"
  log "${engine} update applied successfully"
}

with_lock maintenance apply_update
