#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/lib.sh"

lock_file="${PROJECT_ROOT}/deploy/images.lock"
while (($#)); do
  case "$1" in
    --lock) (($# >= 2)) || die "--lock requires a path"; lock_file="$2"; shift ;;
    -h|--help) printf 'Usage: scripts/resolve-images.sh [--lock deploy/images.lock]\n'; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
  shift
done
[[ -f "$lock_file" ]] || die "image lock does not exist: $lock_file"
require_cmd docker

resolve_one() {
  local var="$1" current base digest
  current="$(awk -F= -v key="$var" '$1 == key {print substr($0, index($0, "=") + 1); exit}' "$lock_file")"
  [[ -n "$current" ]] || die "missing ${var} in ${lock_file}"
  if [[ "$current" =~ @sha256:[0-9a-fA-F]{64}$ ]]; then
    printf '%s\n' "$current"
    return
  fi
  base="${current%%@*}"
  digest="$(docker buildx imagetools inspect "$base" --format '{{.Manifest.Digest}}' | head -n 1)"
  [[ "$digest" =~ ^sha256:[0-9a-fA-F]{64}$ ]] || die "could not resolve immutable digest for ${base}"
  printf '%s@%s\n' "$base" "$digest"
}

misaka="$(resolve_one MISAKA_IMAGE)"
danmu_api="$(resolve_one DANMU_API_IMAGE)"
grep -qE '^MYSQL_IMAGE=mysql:8\.1\.0-oracle$' "$lock_file" || die "MYSQL_IMAGE must remain mysql:8.1.0-oracle"

tmp="$(mktemp "${lock_file}.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
awk -v misaka="$misaka" -v danmu_api="$danmu_api" '
  /^MISAKA_IMAGE=/ {print "MISAKA_IMAGE=" misaka; next}
  /^DANMU_API_IMAGE=/ {print "DANMU_API_IMAGE=" danmu_api; next}
  {print}
' "$lock_file" >"$tmp"
chmod 600 "$tmp"
mv -f -- "$tmp" "$lock_file"
trap - EXIT
printf 'MISAKA_IMAGE=%s\nDANMU_API_IMAGE=%s\n' "$misaka" "$danmu_api"
