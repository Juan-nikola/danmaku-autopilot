#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib.sh"

dry_run=0
rotate=""
yes=0
while (($#)); do
  case "$1" in
    --dry-run) dry_run=1 ;;
    --yes) yes=1 ;;
    --rotate)
      (($# >= 2)) || die "--rotate requires a variable name"
      rotate="$2"; shift
      ;;
    -h|--help)
      printf 'Usage: scripts/bootstrap.sh [--dry-run] [--yes] [--rotate NAME]\n'
      exit 0
      ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

if (( ! yes && ! dry_run )); then
  printf 'This initializes local secrets, Docker volumes, and containers in %s. Continue? [y/N] ' "$PROJECT_ROOT" >&2
  read -r answer
  [[ "$answer" == y || "$answer" == Y ]] || die "bootstrap cancelled"
fi

ensure_dir "$PROJECT_ROOT/state"
ensure_dir "$PROJECT_ROOT/state/secrets"
ensure_dir "$PROJECT_ROOT/state/caddy"
ensure_dir "$PROJECT_ROOT/state/locks"

if [[ ! -e "$ENV_FILE" ]]; then
  [[ -f "$PROJECT_ROOT/config/env.example" ]] || die "missing config/env.example"
  install -m 600 "$PROJECT_ROOT/config/env.example" "$ENV_FILE"
fi
chmod 600 "$ENV_FILE"

# An operator may have started from the repository's root .env.example. Merge
# deployment defaults without overwriting any value they already supplied.
merge_env_defaults() {
  local template="$PROJECT_ROOT/config/env.example" tmp line key
  [[ -f "$template" ]] || die "missing config/env.example"
  tmp="$(mktemp "${PROJECT_ROOT}/state/.env.merge.XXXXXX")"
  chmod 600 "$tmp"
  cp "$ENV_FILE" "$tmp"
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ "$line" =~ ^([A-Z][A-Z0-9_]*)= ]] || continue
    key="${BASH_REMATCH[1]}"
    if ! grep -qE "^${key}=" "$tmp"; then
      printf '%s\n' "$line" >>"$tmp"
    fi
  done <"$template"
  mv -f -- "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}
merge_env_defaults

set_env() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp "${PROJECT_ROOT}/state/.env.XXXXXX")"
  chmod 600 "$tmp"
  if grep -qE "^${key}=" "$ENV_FILE"; then
    awk -v key="$key" -v value="$value" 'index($0, key "=") == 1 {$0=key "=" value} {print}' "$ENV_FILE" >"$tmp"
  else
    cat "$ENV_FILE" >"$tmp"
    printf '%s=%s\n' "$key" "$value" >>"$tmp"
  fi
  mv -f -- "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

value_for() {
  local key="$1"
  awk -v key="$key" 'index($0, key "=") == 1 {sub(/^[^=]*=/, ""); print; exit}' "$ENV_FILE"
}

ensure_random_env() {
  local key="$1" current
  current="$(value_for "$key" || true)"
  if [[ -z "$current" || "$current" == CHANGE_ME* || "$rotate" == "$key" ]]; then
    set_env "$key" "$(random_secret)"
  fi
}

for key in MYSQL_PASSWORD MYSQL_ROOT_PASSWORD MISAKA_CONTROL_KEY DANMU_API_TOKEN PUBLIC_API_TOKEN DEVICE_TOKEN_1 DEVICE_TOKEN_2 DEVICE_TOKEN_3; do
  ensure_random_env "$key"
done

# Keep individual mode-0600 files for operators and backup tooling. Compose uses
# the .env values so `docker compose config` remains useful before bootstrap.
for key in MYSQL_PASSWORD MYSQL_ROOT_PASSWORD MISAKA_CONTROL_KEY DANMU_API_TOKEN PUBLIC_API_TOKEN DEVICE_TOKEN_1 DEVICE_TOKEN_2 DEVICE_TOKEN_3; do
  if [[ "$rotate" == "$key" ]]; then
    (umask 077; printf '%s\n' "$(value_for "$key")" >"$PROJECT_ROOT/state/secrets/${key}")
    chmod 600 "$PROJECT_ROOT/state/secrets/${key}"
  else
    write_secret_once "$PROJECT_ROOT/state/secrets/${key}" "$(value_for "$key")"
  fi
done

if [[ ! -e "$PROJECT_ROOT/deploy/images.lock" ]]; then
  [[ -f "$PROJECT_ROOT/deploy/images.lock.example" ]] || die "missing deploy/images.lock.example"
  install -m 600 "$PROJECT_ROOT/deploy/images.lock.example" "$PROJECT_ROOT/deploy/images.lock"
fi
if (( ! dry_run )) && [[ -x "$PROJECT_ROOT/scripts/resolve-images.sh" ]]; then
  "$PROJECT_ROOT/scripts/resolve-images.sh" --lock "$PROJECT_ROOT/deploy/images.lock"
fi

if (( ! dry_run )); then
  sync_image_env
  set_env MISAKA_IMAGE "$MISAKA_IMAGE"
  set_env DANMU_API_IMAGE "$DANMU_API_IMAGE"
  set_env MYSQL_IMAGE "$MYSQL_IMAGE"
fi

# Caddy reads {$VAR} from its process environment. Keep a generated copy for
# native installs and never expose credentials in the generated file itself.
install -m 600 "$PROJECT_ROOT/config/Caddyfile.native.example" "$PROJECT_ROOT/state/caddy/Caddyfile"

if grep -qE "^CADDY_ADMIN_HASH=(')?(CHANGE_ME|$)" "$ENV_FILE"; then
  log "warning: set CADDY_ADMIN_HASH in .env using 'caddy hash-password' before enabling admin access"
fi

if ((dry_run)); then
  log "dry-run complete; secrets were generated locally but Docker was not contacted"
  exit 0
fi

grep -Eq '^MISAKA_IMAGE=.*@sha256:[0-9a-fA-F]{64}$' "$ENV_FILE" || die "MISAKA_IMAGE must be digest-pinned"
grep -Eq '^DANMU_API_IMAGE=.*@sha256:[0-9a-fA-F]{64}$' "$ENV_FILE" || die "DANMU_API_IMAGE must be digest-pinned"

require_cmd docker
sync_image_env
docker compose --project-directory "$PROJECT_ROOT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet
docker compose --project-directory "$PROJECT_ROOT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d

for _ in {1..60}; do
  if docker compose --project-directory "$PROJECT_ROOT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps --status running --format '{{.Service}}' | grep -qx autopilot; then
    break
  fi
  sleep 2
done

"${SCRIPT_DIR}/healthcheck.sh"
api_host="$(value_for DANMU_API_HOST)"
token="$(value_for PUBLIC_API_TOKEN)"
log "bootstrap complete"
printf 'Forward/SenPlayer API: https://%s/api?token=%s\n' "$api_host" "$(printf '%s' "$token" | sed -E 's/^(.{4}).*(.{4})$/\1…\2/')" | redact_url
printf 'Admin UI: https://%s\n' "$(value_for DANMU_ADMIN_HOST)"
