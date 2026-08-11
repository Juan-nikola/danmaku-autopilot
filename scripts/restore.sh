#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib.sh"

usage() { printf 'Usage: scripts/restore.sh <backup-id> --verify|--apply\n'; }

backup_id=""
mode=""
while (($#)); do
  case "$1" in
    --verify|--apply) [[ -z "$mode" ]] || die "choose only one restore mode"; mode="${1#--}" ;;
    -h|--help) usage; exit 0 ;;
    -*) die "unknown option: $1" ;;
    *) [[ -z "$backup_id" ]] || die "only one backup id is accepted"; backup_id="$1" ;;
  esac
  shift
done
[[ -n "$backup_id" && -n "$mode" ]] || { usage >&2; exit 2; }
[[ "$backup_id" =~ ^[A-Za-z0-9._-]+$ ]] || die "invalid backup id"
[[ -d "$BACKUP_DIR" ]] || die "backup directory does not exist"
backup_path="${BACKUP_DIR}/${backup_id}"
safe_backup_path "$backup_path" >/dev/null
[[ -f "$backup_path/manifest.json" ]] || die "manifest is missing for ${backup_id}"

verify_backup() {
  python3 - "$backup_path/manifest.json" "$backup_path/files" <<'PY'
import hashlib, json, pathlib, sys
manifest_path = pathlib.Path(sys.argv[1])
payload = pathlib.Path(sys.argv[2])
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
required = {"format_version", "created_at", "reason", "misaka_release", "images", "sha256", "files"}
missing = required - manifest.keys()
if missing:
    raise SystemExit(f"manifest missing fields: {sorted(missing)}")
for rel, expected in manifest["sha256"].items():
    path = payload / rel
    if not path.is_file():
        raise SystemExit(f"missing backup file: {rel}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f"checksum mismatch: {rel}")
print(f"verified {manifest['backup_id']} ({len(manifest['files'])} files)")
PY
  if [[ -f "$backup_path/files/autopilot.db" && -n "$(command -v sqlite3 || true)" ]]; then
    [[ "$(sqlite3 "$backup_path/files/autopilot.db" 'PRAGMA integrity_check;' | tr -d '\r')" == ok ]] || die "SQLite integrity check failed"
  fi
  [[ -s "$backup_path/files/mysql.sql" ]] || die "MySQL dump is empty"
}

verify_backup
if [[ "$mode" == verify ]]; then
  log "refusing restore: verification requested without --apply; production was not stopped"
  exit 0
fi

[[ "$mode" == apply ]] || die "restore requires --apply"
load_env
require_cmd docker
log "--apply requested; creating a safety backup before restore"
"${SCRIPT_DIR}/backup.sh" --reason manual >/dev/null

# Only application services are stopped. Unrelated Docker projects are untouched.
compose stop autopilot misaka danmu-api
compose up -d mysql
for _ in {1..60}; do
  if compose ps --status running --format '{{.Service}}' | grep -qx mysql; then break; fi
  sleep 2
done
compose exec -T mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' <"$backup_path/files/mysql.sql"

if [[ -s "$backup_path/files/misaka-app.tar.gz" ]]; then
  compose cp "$backup_path/files/misaka-app.tar.gz" misaka:/tmp/misaka-app.tar.gz
  compose exec -T misaka sh -c 'tar -C /app -xzf /tmp/misaka-app.tar.gz && rm -f /tmp/misaka-app.tar.gz'
fi
if [[ -s "$backup_path/files/danmu-api-app.tar.gz" ]]; then
  compose cp "$backup_path/files/danmu-api-app.tar.gz" danmu-api:/tmp/danmu-api-app.tar.gz
  compose exec -T danmu-api sh -c 'tar -C /app -xzf /tmp/danmu-api-app.tar.gz && rm -f /tmp/danmu-api-app.tar.gz'
fi

if [[ -f "$backup_path/files/autopilot.db" ]]; then
  ensure_dir "$PROJECT_ROOT/state"
  cp -p -- "$backup_path/files/autopilot.db" "$PROJECT_ROOT/state/autopilot.db"
fi
if [[ -f "$backup_path/files/images.lock" ]]; then
  cp -p -- "$backup_path/files/images.lock" "$PROJECT_ROOT/deploy/images.lock"
fi
compose up -d misaka danmu-api autopilot
"${SCRIPT_DIR}/healthcheck.sh"
log "restore applied and health checks passed: ${backup_id}"
