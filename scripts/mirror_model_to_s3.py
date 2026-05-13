#!/usr/bin/env python3
"""Mirror one local model file to S3 and print a registry row suggestion.

S3 configuration:
  MODEL_S3_BUCKET or S3_BUCKET is required for upload operations.
  MODEL_S3_PREFIX or S3_PREFIX defaults to "comfyui".
  AWS_PROFILE and AWS_REGION/AWS_DEFAULT_REGION are honored by the AWS CLI.

The --s3-uri argument may include ${MODEL_S3_BUCKET} and ${MODEL_S3_PREFIX}
placeholders. They are expanded at runtime and preserved in the suggested row.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from model_resolver_lib import (  # noqa: E402
    CSV_FIELDS,
    SOURCE_DEFAULTS,
    default_s3_uri_for,
    expand_s3_uri,
    log,
    mirror_policy_for,
    require_s3_bucket,
    sha256_file,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--s3-uri", default="")
    parser.add_argument("--source-url", default="")
    parser.add_argument("--source-type", default="manual_private")
    parser.add_argument("--workspace-path", default="")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.file.exists():
        raise SystemExit(f"Model file not found: {args.file}")

    workspace_path = args.workspace_path or str(args.file).replace("\\", "/")
    s3_uri = args.s3_uri or default_s3_uri_for(workspace_path)
    require_s3_bucket()

    command = ["aws", "s3", "cp", str(args.file), expand_s3_uri(s3_uri)]
    if args.dry_run:
        log(f"Dry run: {' '.join(command)}")
    else:
        log(f"Uploading {args.file} to {expand_s3_uri(s3_uri)}")
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            raise SystemExit(completed.returncode)

    digest = sha256_file(args.file)
    row = {
        "model_filename": args.file.name,
        "canonical_url": args.source_url,
        "workspace_path": workspace_path,
        "source_type": args.source_type,
        "mirror_policy": mirror_policy_for(args.source_type, SOURCE_DEFAULTS),
        "s3_uri": s3_uri,
        "sha256": digest,
        "confidence": "high",
        "notes": "Suggested row from mirror_model_to_s3.py.",
    }
    writer = csv.DictWriter(sys.stdout, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerow(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
