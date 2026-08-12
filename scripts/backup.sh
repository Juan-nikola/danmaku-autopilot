#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib.sh"

reason="manual"
while (($#)); do
  case "$1" in
    --reason)
      (($# >= 2)) || die "--reason requires daily, pre-update, or manual"
      reason="$2"; shift
      ;;
    -h|--help) printf 'Usage: scripts/backup.sh --reason daily|pre-update|manual\n'; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done
[[ "$reason" == daily || "$reason" == pre-update || "$reason" == manual ]] || die "invalid backup reason"

load_env
ensure_dir "$BACKUP_DIR"

backup_one() {
  local stamp backup_id tmp final payload
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  backup_id="${stamp}-${reason}"
  tmp="${BACKUP_DIR}/.${backup_id}.tmp"
  final="${BACKUP_DIR}/${backup_id}"
  payload="${tmp}/files"
  [[ ! -e "$final" && ! -e "$tmp" ]] || die "backup already exists: $backup_id"
  mkdir -p -- "$payload"
  trap 'find "$tmp" -depth -type f -delete 2>/dev/null || true; find "$tmp" -depth -type d -empty -delete 2>/dev/null || true' RETURN

  compose exec -T mysql sh -c 'mysqldump --single-transaction --routines --events --hex-blob -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' >"$payload/mysql.sql"

  if [[ -f "$PROJECT_ROOT/state/autopilot.db" && -n "$(command -v sqlite3 || true)" ]]; then
    sqlite3 "$PROJECT_ROOT/state/autopilot.db" 'PRAGMA wal_checkpoint(TRUNCATE);' >/dev/null
    cp -p -- "$PROJECT_ROOT/state/autopilot.db" "$payload/autopilot.db"
  fi
  [[ -f "$PROJECT_ROOT/deploy/images.lock" ]] && cp -p -- "$PROJECT_ROOT/deploy/images.lock" "$payload/images.lock"
  [[ -f "$ENV_FILE" ]] && cp -p -- "$ENV_FILE" "$payload/.env"
  [[ -d "$PROJECT_ROOT/state/secrets" ]] && tar -C "$PROJECT_ROOT/state" -czf "$payload/secrets.tar.gz" secrets

  # Preserve engine config/cache trees without exposing Docker's socket.
  compose exec -T misaka sh -c 'tar -C /app -czf - config cache' >"$payload/misaka-app.tar.gz" || log "warning: Misaka config/cache archive unavailable"
  compose exec -T danmu-api sh -c 'tar -C /app -czf - .cache config' >"$payload/danmu-api-app.tar.gz" || log "warning: danmu_api config/cache archive unavailable"

  local manifest_tmp="${tmp}/manifest.json"
  BACKUP_ID="$backup_id" BACKUP_REASON="$reason" MISAKA_RELEASE="${MISAKA_RELEASE:-unknown}" \
    python3 - "$payload" "$manifest_tmp" <<'PY'
import hashlib, json, os, pathlib, sys
payload = pathlib.Path(sys.argv[1])
manifest_path = pathlib.Path(sys.argv[2])
files = {}
for path in sorted(p for p in payload.rglob("*") if p.is_file()):
    files[str(path.relative_to(payload))] = hashlib.sha256(path.read_bytes()).hexdigest()
manifest = {
    "format_version": 1,
    "backup_id": os.environ["BACKUP_ID"],
    "created_at": os.environ["BACKUP_ID"].split("-", 1)[0],
    "reason": os.environ["BACKUP_REASON"],
    "misaka_release": os.environ.get("MISAKA_RELEASE", "unknown"),
    "images": {
        "misaka": os.environ.get("MISAKA_IMAGE", "unknown"),
        "danmu_api": os.environ.get("DANMU_API_IMAGE", "unknown"),
        "mysql": os.environ.get("MYSQL_IMAGE", "mysql:8.1.0-oracle"),
    },
    "sha256": files,
    "files": sorted(files),
}
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  mv -- "$tmp" "$final"
  trap - RETURN
  if [[ -n "${RESTIC_REPOSITORY:-}" ]]; then
    if have restic; then
      [[ -n "${RESTIC_PASSWORD_FILE:-}" ]] || die "RESTIC_PASSWORD_FILE is required when RESTIC_REPOSITORY is set"
      restic backup "$final" --tag "danmu-${reason}" >/dev/null
      restic check --read-data-subset=1/20 >/dev/null
    else
      die "RESTIC_REPOSITORY is set but restic is not installed"
    fi
  fi
  BACKUP_ROOT="$BACKUP_DIR" python3 - <<'PY'
import os, pathlib, shutil
root = pathlib.Path(os.environ["BACKUP_ROOT"]).resolve()
if root in (pathlib.Path("/"), pathlib.Path.cwd().resolve()):
    raise SystemExit("refusing retention cleanup for a broad backup directory")
entries = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
for reason, limit in (("daily", 14), ("pre-update", 5)):
    matching = sorted((p for p in entries if p.name.endswith("-" + reason)), reverse=True)
    for old in matching[limit:]:
        if old.parent == root and old.name.count("-") >= 2:
            shutil.rmtree(old)
PY
  log "created backup ${backup_id}"
  printf '%s\n' "$backup_id"
}

with_lock backup backup_one
