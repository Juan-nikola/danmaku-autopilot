#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib.sh"

repair=0
while (($#)); do
  case "$1" in
    --repair) repair=1 ;;
    -h|--help) printf 'Usage: scripts/healthcheck.sh [--repair]\n'; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done

load_env
require_cmd curl

if ! compose ps --status running --format '{{.Service}}' | grep -qx 'autopilot'; then
  if ((repair)); then
    log "autopilot is not running; restarting only the named application service"
    compose up -d --no-deps autopilot
  else
    die "autopilot is not running"
  fi
fi

curl --fail --silent --show-error --max-time 10 http://127.0.0.1:"${AUTOPILOT_BIND_PORT:-7770}"/healthz >/dev/null \
  || die "autopilot health endpoint failed"
curl --fail --silent --show-error --max-time 10 http://127.0.0.1:"${MISAKA_BIND_PORT:-7768}"/ >/dev/null \
  || die "Misaka health endpoint failed"

if [[ -n "${DANMU_API_HOST:-}" ]]; then
  curl --fail --silent --show-error --max-time 15 \
    -H "Host: ${DANMU_API_HOST}" "https://${DANMU_API_HOST}/healthz" >/dev/null \
    || log "warning: public player endpoint is not reachable from this host"
fi

log "all required application health checks passed"
