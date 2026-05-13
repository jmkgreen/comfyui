#!/usr/bin/env python3
"""Ensure reviewed ComfyUI model CSV entries exist locally.

S3 configuration:
  MODEL_S3_BUCKET or S3_BUCKET is required for S3 restore/upload operations.
  MODEL_S3_PREFIX or S3_PREFIX defaults to "comfyui".
  AWS_PROFILE and AWS_REGION/AWS_DEFAULT_REGION are honored by the AWS CLI.

Authentication:
  HF_TOKEN and CIVITAI_TOKEN are read at runtime only. Tokens are never written
  to the manifest, logs, or generated files.
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from model_resolver_lib import (  # noqa: E402
    default_s3_uri_for,
    die,
    expand_s3_uri,
    load_source_policy,
    log,
    mirror_policy_for,
    normalize_row,
    prefer_s3_restore,
    redact,
    require_s3_bucket,
    sha256_file,
    token_env_for,
    warn,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="models.resolved.csv", type=Path)
    parser.add_argument("--source-policy", default="config/source_policy.yaml", type=Path)
    parser.add_argument("--models-root", default="/workspace/models")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mirror-after-download", action="store_true", help="Allow post-download S3 mirroring.")
    return parser.parse_args()


def workspace_destination(workspace_path: str, models_root: str) -> Path:
    normalized = workspace_path.replace("\\", "/")
    if normalized.startswith("/workspace/models/"):
        return Path(models_root) / normalized.removeprefix("/workspace/models/")
    return Path(normalized)


def run_aws(args, dry_run: bool) -> bool:
    command = ["aws", *args]
    if dry_run:
        log(f"Dry run: {' '.join(command)}")
        return True
    log(f"Running: {' '.join(command)}")
    completed = subprocess.run(command, check=False)
    return completed.returncode == 0


def auth_headers(source_type: str, policies: Dict[str, Dict[str, object]]) -> Dict[str, str]:
    token_env = token_env_for(source_type, policies)
    if not token_env:
        return {}
    token = os.environ.get(token_env)
    if not token:
        die(f"{source_type} requires {token_env}, but it is not set.")
    if token_env == "HF_TOKEN":
        return {"Authorization": f"Bearer {token}"}
    return {}


def authenticated_url(url: str, source_type: str, policies: Dict[str, Dict[str, object]]) -> str:
    token_env = token_env_for(source_type, policies)
    if token_env != "CIVITAI_TOKEN":
        return url
    token = os.environ.get(token_env)
    if not token:
        die(f"{source_type} requires {token_env}, but it is not set.")
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    query["token"] = [token]
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query, doseq=True)))


def download(url: str, destination: Path, source_type: str, policies: Dict[str, Dict[str, object]], dry_run: bool) -> bool:
    safe_url = redact(authenticated_url(url, source_type, policies))
    if dry_run:
        log(f"Dry run: download {safe_url} to {destination}")
        return True

    destination.parent.mkdir(parents=True, exist_ok=True)
    request_url = authenticated_url(url, source_type, policies)
    request = urllib.request.Request(request_url, headers=auth_headers(source_type, policies))
    log(f"Downloading {safe_url} to {destination}")
    tmp = destination.with_suffix(destination.suffix + ".partial")
    try:
        with urllib.request.urlopen(request, timeout=60) as response, tmp.open("wb") as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        tmp.replace(destination)
        return True
    except Exception as exc:  # noqa: BLE001
        warn(f"Download failed for {destination.name}: {redact(str(exc))}")
        if tmp.exists():
            tmp.unlink()
        return False


def restore_from_s3(s3_uri: str, destination: Path, dry_run: bool) -> bool:
    require_s3_bucket()
    destination.parent.mkdir(parents=True, exist_ok=True)
    return run_aws(["s3", "cp", expand_s3_uri(s3_uri), str(destination)], dry_run)


def upload_to_s3(s3_uri: str, source: Path, dry_run: bool) -> bool:
    require_s3_bucket()
    return run_aws(["s3", "cp", str(source), expand_s3_uri(s3_uri)], dry_run)


def load_manifest(path: Path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield normalize_row(row)


def main() -> int:
    args = parse_args()
    policies = load_source_policy(args.source_policy)
    failures = 0

    for row in load_manifest(args.manifest):
        filename = row["model_filename"]
        destination = workspace_destination(row["workspace_path"], args.models_root)
        source_type = row["source_type"]
        mirror_policy = row["mirror_policy"] or mirror_policy_for(source_type, policies)
        s3_uri = row["s3_uri"] or default_s3_uri_for(row["workspace_path"])

        if destination.exists():
            log(f"Present: {destination}")
            continue

        restored = False
        if s3_uri and prefer_s3_restore(source_type, policies):
            log(f"Missing: {filename}; restoring from S3 first.")
            restored = restore_from_s3(s3_uri, destination, args.dry_run)
            if not restored:
                warn(f"S3 restore failed for {filename}; trying canonical URL if available.")

        if not restored:
            if not row["canonical_url"]:
                warn(f"No canonical_url for missing model {filename}.")
                failures += 1
                continue
            if not download(row["canonical_url"], destination, source_type, policies, args.dry_run):
                failures += 1
                continue

        if row["sha256"] and not args.dry_run:
            actual = sha256_file(destination)
            if actual.lower() != row["sha256"].lower():
                warn(f"SHA-256 mismatch for {filename}: expected {row['sha256']}, got {actual}")
                failures += 1
                continue

        if mirror_policy == "mirror_after_download":
            if args.mirror_after_download:
                log(f"Mirroring {filename} to S3 after successful download.")
                if not upload_to_s3(s3_uri, destination, args.dry_run):
                    failures += 1
            else:
                warn(f"{filename} is marked mirror_after_download; pass --mirror-after-download to upload it.")

    if failures:
        die(f"{failures} model(s) could not be ensured.")
    log("All reviewed models are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
