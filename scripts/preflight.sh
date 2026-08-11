#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib.sh"

usage() {
  cat <<'EOF'
Usage: scripts/preflight.sh [--json]

Read-only checks for Docker, Compose, DNS, disk space, and required local ports.
EOF
}

json=0
while (($#)); do
  case "$1" in
    --json) json=1 ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

load_env
require_cmd docker

docker_ok=1
if ! docker info >/dev/null 2>&1; then docker_ok=0; fi
compose_ok=1
if ! sync_image_env >/dev/null 2>&1; then
  compose_ok=0
elif ! docker compose --project-directory "$PROJECT_ROOT" --env-file "$ENV_FILE" -f "$COMPOSE_FILE" config --quiet >/dev/null 2>&1; then
  compose_ok=0
fi

dns_api="unknown"
dns_admin="unknown"
if have getent; then
  getent hosts "${DANMU_API_HOST:-}" >/dev/null 2>&1 && dns_api=ok || dns_api=failed
  getent hosts "${DANMU_ADMIN_HOST:-}" >/dev/null 2>&1 && dns_admin=ok || dns_admin=failed
else
  log "warning: getent is unavailable; DNS checks skipped"
fi

disk_available_kb="$(df -Pk "$PROJECT_ROOT" | awk 'NR==2 {print $4}')"
disk_available_kb="${disk_available_kb:-0}"
port_misaka="free"
port_autopilot="free"
if have lsof; then
  lsof -nP -iTCP:"${MISAKA_BIND_PORT:-7768}" -sTCP:LISTEN >/dev/null 2>&1 && port_misaka=busy || true
  lsof -nP -iTCP:"${AUTOPILOT_BIND_PORT:-7770}" -sTCP:LISTEN >/dev/null 2>&1 && port_autopilot=busy || true
fi

if ((json)); then
  printf '{"docker":%s,"compose":%s,"dns_api":"%s","dns_admin":"%s","disk_available_kb":%s,"misaka_port":"%s","autopilot_port":"%s"}\n' \
    "$docker_ok" "$compose_ok" "$dns_api" "$dns_admin" "$disk_available_kb" "$port_misaka" "$port_autopilot"
else
  printf 'Docker: %s\nCompose: %s\nDNS player: %s\nDNS admin: %s\nDisk available: %s KiB\nMisaka bind port: %s\nAutopilot bind port: %s\n' \
    "$([[ $docker_ok == 1 ]] && echo ok || echo failed)" \
    "$([[ $compose_ok == 1 ]] && echo ok || echo failed)" \
    "$dns_api" "$dns_admin" "$disk_available_kb" "$port_misaka" "$port_autopilot"
fi

((docker_ok && compose_ok)) || die "preflight failed; fix Docker or Compose before continuing"
