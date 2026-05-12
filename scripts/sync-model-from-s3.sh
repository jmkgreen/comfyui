#!/usr/bin/env bash
set -Eeuo pipefail

die() {
  printf '[sync-model-from-s3] ERROR: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[sync-model-from-s3] %s\n' "$*"
}

S3_BUCKET="${S3_BUCKET:-}"
S3_PREFIX="${S3_PREFIX:-comfyui}"
MODELS_DIR="${MODELS_DIR:-/workspace/models}"
DRY_RUN="${DRY_RUN:-0}"

[[ -n "${S3_BUCKET}" ]] || die "Set S3_BUCKET to the bucket that stores your ComfyUI files."
command -v aws >/dev/null 2>&1 || die "Missing required command: aws"

[[ $# -ge 1 && $# -le 2 ]] || die "Usage: S3_BUCKET=my-bucket $0 <s3-relative-path> [local-relative-path]"

s3_relative="$1"
local_relative="${2:-${s3_relative#models/}}"
source_uri="s3://${S3_BUCKET}/${S3_PREFIX}/${s3_relative}"
destination="${MODELS_DIR}/${local_relative}"

mkdir -p "$(dirname "${destination}")"

if [[ "${s3_relative}" == */ ]]; then
  log "Syncing prefix ${source_uri} to ${destination}/"
  if [[ "${DRY_RUN}" == "1" ]]; then
    aws s3 sync --dryrun "${source_uri}" "${destination}/"
  else
    aws s3 sync "${source_uri}" "${destination}/"
  fi
else
  log "Copying ${source_uri} to ${destination}"
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "Dry run: aws s3 cp ${source_uri} ${destination}"
  else
    aws s3 cp "${source_uri}" "${destination}"
  fi
fi
