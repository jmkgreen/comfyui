#!/usr/bin/env bash
set -Eeuo pipefail

# Sync generated ComfyUI outputs to a date-based S3 prefix.
#
# S3 configuration:
#   MODEL_S3_BUCKET or S3_BUCKET is required.
#   MODEL_S3_PREFIX or S3_PREFIX defaults to "comfyui".
#   AWS_PROFILE and AWS_REGION/AWS_DEFAULT_REGION are honored by the AWS CLI.

die() {
  printf '[sync-generations-to-s3] ERROR: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[sync-generations-to-s3] %s\n' "$*"
}

bucket="${MODEL_S3_BUCKET:-${S3_BUCKET:-}}"
prefix="${MODEL_S3_PREFIX:-${S3_PREFIX:-comfyui}}"
output_dir="${OUTPUT_DIR:-/workspace/output}"
date_label="${DATE_LABEL:-$(date -u +%F)}"
dry_run="${DRY_RUN:-0}"

[[ -n "${bucket}" ]] || die "Set MODEL_S3_BUCKET or S3_BUCKET before syncing generations."
[[ -d "${output_dir}" ]] || die "Output directory not found: ${output_dir}"
command -v aws >/dev/null 2>&1 || die "Missing required command: aws"
[[ $# -le 1 ]] || die "Usage: $0 [s3://bucket/prefix]"

if [[ $# -eq 1 ]]; then
  base_destination="${1%/}"
else
  base_destination="s3://${bucket}/${prefix}/generations"
fi

destination="${base_destination}/${date_label}/"

log "Syncing ${output_dir}/ to ${destination}"
if [[ "${dry_run}" == "1" ]]; then
  aws s3 sync --dryrun "${output_dir}/" "${destination}"
else
  aws s3 sync "${output_dir}/" "${destination}"
fi
