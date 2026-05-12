#!/usr/bin/env bash
set -Eeuo pipefail

die() {
  printf '[push-generations-to-s3] ERROR: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[push-generations-to-s3] %s\n' "$*"
}

S3_BUCKET="${S3_BUCKET:-}"
OUTPUT_DIR="${OUTPUT_DIR:-/workspace/output}"
GENERATION_S3_PREFIX="${GENERATION_S3_PREFIX:-${S3_PREFIX:-comfyui}/generations}"
RUN_LABEL="${RUN_LABEL:-$(date -u +%H%M%S)}"
DATE_LABEL="${DATE_LABEL:-$(date -u +%F)}"
DRY_RUN="${DRY_RUN:-0}"

[[ -n "${S3_BUCKET}" ]] || die "Set S3_BUCKET to the bucket that stores your ComfyUI files."
[[ -d "${OUTPUT_DIR}" ]] || die "Output directory not found: ${OUTPUT_DIR}"
command -v aws >/dev/null 2>&1 || die "Missing required command: aws"

destination="s3://${S3_BUCKET}/${GENERATION_S3_PREFIX}/${DATE_LABEL}/${RUN_LABEL}/"

log "Syncing ${OUTPUT_DIR}/ to ${destination}"
if [[ "${DRY_RUN}" == "1" ]]; then
  aws s3 sync --dryrun "${OUTPUT_DIR}/" "${destination}"
else
  aws s3 sync "${OUTPUT_DIR}/" "${destination}"
fi
