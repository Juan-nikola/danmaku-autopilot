#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib.sh"

apply=0
while (($#)); do
  case "$1" in
    --apply) apply=1 ;;
    -h|--help) printf 'Usage: scripts/cloudflare-dns.sh [--apply]\n'; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done
load_env

[[ -n "${CF_API_TOKEN:-}" ]] || die "CF_API_TOKEN is required"
[[ -n "${CF_ZONE_ID:-}" ]] || die "CF_ZONE_ID is required"
require_cmd curl

api="https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/dns_records"
auth=(-H "Authorization: Bearer ${CF_API_TOKEN}" -H 'Content-Type: application/json')
public_ip="${DANMU_PUBLIC_IP:-}"
if [[ -z "$public_ip" ]]; then
  public_ip="$(curl --fail --silent --show-error --max-time 10 https://api.ipify.org)"
fi

for hostname in "${DANMU_API_HOST}" "${DANMU_ADMIN_HOST}"; do
  payload="$(printf '{"type":"A","name":"%s","content":"%s","ttl":300,"proxied":false}' "$hostname" "$public_ip")"
  existing="$(curl --fail --silent --show-error "${api}?type=A&name=${hostname}" "${auth[@]}")"
  printf '%s -> %s (A, proxied=false)\n' "$hostname" "$public_ip"
  if ((apply == 0)); then
    continue
  fi
  if [[ "$existing" == *'"result":[]'* ]]; then
    curl --fail --silent --show-error -X POST "${auth[@]}" --data "$payload" "$api" >/dev/null
  else
    record_id="$(printf '%s' "$existing" | sed -nE 's/.*"id":"([^"]+)".*/\1/p' | head -n 1)"
    [[ -n "$record_id" ]] || die "could not parse Cloudflare record id for ${hostname}"
    curl --fail --silent --show-error -X PUT "${auth[@]}" --data "$payload" "${api}/${record_id}" >/dev/null
  fi
done

((apply)) || log "dry-run only; rerun with --apply after reviewing the two exact records"
