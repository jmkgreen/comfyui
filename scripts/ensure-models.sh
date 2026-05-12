#!/usr/bin/env bash
set -Eeuo pipefail

log() {
  printf '[ensure-models] %s\n' "$*"
}

die() {
  printf '[ensure-models] ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-comfyui}"
MODEL_MANIFEST="${MODEL_MANIFEST:-/workspace/config/essential-models.txt}"
MODELS_DIR="${MODELS_DIR:-/workspace/models}"
DRY_RUN="${DRY_RUN:-0}"

[[ -n "${S3_BUCKET}" ]] || die "Set S3_BUCKET to the bucket that stores your ComfyUI files."
[[ -f "${MODEL_MANIFEST}" ]] || die "Model manifest not found: ${MODEL_MANIFEST}"
require_command aws

mkdir -p "${MODELS_DIR}"
failures=0

while IFS= read -r line || [[ -n "${line}" ]]; do
  line="${line%%#*}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  [[ -n "${line}" ]] || continue

  read -r s3_relative local_relative extra <<<"${line}"
  if [[ -z "${s3_relative:-}" || -z "${local_relative:-}" || -n "${extra:-}" ]]; then
    log "Invalid manifest line: ${line}"
    failures=$((failures + 1))
    continue
  fi

  destination="${MODELS_DIR}/${local_relative}"
  source_uri="s3://${S3_BUCKET}/${S3_PREFIX}/${s3_relative}"

  if [[ -f "${destination}" ]]; then
    log "Present: ${local_relative}"
    continue
  fi

  log "Missing: ${local_relative}; copying from ${source_uri}"
  mkdir -p "$(dirname "${destination}")"
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "Dry run: aws s3 cp ${source_uri} ${destination}"
  elif ! aws s3 cp "${source_uri}" "${destination}"; then
    log "Failed to copy ${source_uri}"
    rm -f "${destination}"
    failures=$((failures + 1))
  fi
done < "${MODEL_MANIFEST}"

if [[ "${failures}" -gt 0 ]]; then
  die "${failures} required model(s) could not be restored."
fi

log "All required models are present."
