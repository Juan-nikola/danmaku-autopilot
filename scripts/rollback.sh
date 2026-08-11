#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib.sh"

selector=""
yes=0
while (($#)); do
  case "$1" in
    --yes) yes=1 ;;
    -h|--help) printf 'Usage: scripts/rollback.sh latest|<backup-id> [--yes]\n'; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *) [[ -z "$selector" ]] || die "only one rollback selector is accepted"; selector="$1" ;;
  esac
  shift
done
[[ -n "$selector" ]] || die "rollback requires latest or an explicit backup id"
load_env

if [[ "$selector" == latest ]]; then
  [[ -d "$PROJECT_ROOT/state/versions" ]] || die "no successful versions recorded"
  # Version records contain the backup id on their first line.
  version_file="$(find "$PROJECT_ROOT/state/versions" -type f -name '*.successful' -print | sort | tail -n 1)"
  [[ -n "$version_file" ]] || die "no successful versions recorded"
  selector="$(head -n 1 "$version_file")"
fi
[[ "$selector" =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid rollback selector"
[[ -d "${BACKUP_DIR}/${selector}" ]] || die "no backup found for ${selector}"

if (( ! yes )); then
  printf 'Rollback will restore %s and restart danmaku services. Continue? [y/N] ' "$selector" >&2
  read -r answer
  [[ "$answer" == y || "$answer" == Y ]] || die "rollback cancelled"
fi

log "creating safety backup before rollback"
"${SCRIPT_DIR}/backup.sh" --reason manual >/dev/null
"${SCRIPT_DIR}/restore.sh" "$selector" --apply
log "rollback completed: ${selector}"
