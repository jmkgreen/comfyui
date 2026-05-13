#!/usr/bin/env python3
"""Shared helpers for ComfyUI model resolver scripts.

S3 configuration:
  MODEL_S3_BUCKET is required whenever a script needs to upload, restore, or
  expand an S3 placeholder.
  MODEL_S3_PREFIX defaults to "comfyui".
  AWS_PROFILE and AWS_REGION/AWS_DEFAULT_REGION are honored by the AWS CLI.
"""

from __future__ import annotations

import csv
import fnmatch
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional


CSV_FIELDS = [
    "model_filename",
    "canonical_url",
    "workspace_path",
    "source_type",
    "mirror_policy",
    "s3_uri",
    "sha256",
    "confidence",
    "notes",
]


SOURCE_DEFAULTS = {
    "huggingface_public": {
        "canonical": "public_url",
        "mirror_to_s3": False,
        "prefer_s3_restore": False,
        "token_env": "HF_TOKEN",
    },
    "huggingface_gated": {
        "canonical": "public_url",
        "mirror_to_s3": True,
        "prefer_s3_restore": True,
        "token_env": "HF_TOKEN",
    },
    "civitai_public": {
        "canonical": "public_url",
        "mirror_to_s3": False,
        "prefer_s3_restore": False,
        "token_env": None,
    },
    "civitai_gated": {
        "canonical": "public_url",
        "mirror_to_s3": True,
        "prefer_s3_restore": True,
        "token_env": "CIVITAI_TOKEN",
    },
    "manual_private": {
        "canonical": "s3",
        "mirror_to_s3": True,
        "prefer_s3_restore": True,
        "token_env": None,
    },
}


def log(message: str) -> None:
    print(f"[model-resolver] {message}", file=sys.stderr)


def warn(message: str) -> None:
    print(f"[model-resolver] WARNING: {message}", file=sys.stderr)


def die(message: str) -> None:
    print(f"[model-resolver] ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_model_filenames(path: Path) -> List[str]:
    filenames: List[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.split("#", 1)[0].strip()
            if line:
                filenames.append(line)
    return filenames


def read_registry(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: Dict[str, Dict[str, str]] = {}
        for row in reader:
            filename = (row.get("model_filename") or "").strip()
            if filename:
                rows[filename] = normalize_row(row)
        return rows


def normalize_row(row: Dict[str, str]) -> Dict[str, str]:
    normalized = {field: (row.get(field) or "").strip() for field in CSV_FIELDS}
    if not normalized["model_filename"]:
        normalized["model_filename"] = Path(normalized["workspace_path"]).name
    return normalized


def write_rows(path: Path, rows: Iterable[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(normalize_row(row))


def parse_scalar(value: str):
    value = value.strip().strip('"').strip("'")
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() in {"null", "none", "~"}:
        return None
    return value


def load_source_policy(path: Path) -> Dict[str, Dict[str, object]]:
    if not path.exists():
        return SOURCE_DEFAULTS.copy()

    sources: Dict[str, Dict[str, object]] = {}
    current: Optional[str] = None
    in_sources = False
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            if line == "sources:":
                in_sources = True
                continue
            if not in_sources:
                continue
            source_match = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
            if source_match:
                current = source_match.group(1)
                sources[current] = {}
                continue
            value_match = re.match(r"^    ([A-Za-z0-9_.-]+):\s*(.*)$", line)
            if current and value_match:
                sources[current][value_match.group(1)] = parse_scalar(value_match.group(2))

    merged = {key: value.copy() for key, value in SOURCE_DEFAULTS.items()}
    for source_type, config in sources.items():
        merged.setdefault(source_type, {}).update(config)
    return merged


def load_path_rules(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return [
            {"match": "*vae*", "path": "vae"},
            {"match": "*lora*", "path": "loras"},
            {"match": "*controlnet*", "path": "controlnet"},
            {"match": "*clip*", "path": "clip"},
            {"match": "t5xxl*", "path": "clip"},
            {"match": "*unet*", "path": "unet"},
            {"match": "flux1-*.safetensors", "path": "unet"},
            {"match": "*.safetensors", "path": "checkpoints"},
            {"match": "*.ckpt", "path": "checkpoints"},
        ]

    rules: List[Dict[str, str]] = []
    current: Dict[str, str] = {}
    in_rules = False
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            if line == "rules:":
                in_rules = True
                continue
            if not in_rules:
                continue
            item_match = re.match(r"^  - match:\s*(.*)$", line)
            if item_match:
                if current:
                    rules.append(current)
                current = {"match": str(parse_scalar(item_match.group(1)))}
                continue
            path_match = re.match(r"^    path:\s*(.*)$", line)
            if path_match and current:
                current["path"] = str(parse_scalar(path_match.group(1)))
        if current:
            rules.append(current)
    return [rule for rule in rules if "match" in rule and "path" in rule]


def infer_workspace_path(filename: str, rules: List[Dict[str, str]], models_root: str) -> str:
    lower_name = filename.lower()
    for rule in rules:
        if fnmatch.fnmatch(lower_name, rule["match"].lower()):
            return str(Path(models_root) / rule["path"] / filename).replace("\\", "/")
    return str(Path(models_root) / "checkpoints" / filename).replace("\\", "/")


def mirror_policy_for(source_type: str, policies: Dict[str, Dict[str, object]]) -> str:
    policy = policies.get(source_type, {})
    if policy.get("canonical") == "s3":
        return "s3_primary"
    if policy.get("mirror_to_s3"):
        return "mirror_after_download"
    return "never"


def prefer_s3_restore(source_type: str, policies: Dict[str, Dict[str, object]]) -> bool:
    return bool(policies.get(source_type, {}).get("prefer_s3_restore"))


def token_env_for(source_type: str, policies: Dict[str, Dict[str, object]]) -> Optional[str]:
    value = policies.get(source_type, {}).get("token_env")
    return str(value) if value else None


def redact(text: str) -> str:
    redacted = text
    for key, value in os.environ.items():
        if key.endswith("TOKEN") and value:
            redacted = redacted.replace(value, "[REDACTED]")
    return redacted


def require_s3_bucket() -> str:
    bucket = os.environ.get("MODEL_S3_BUCKET") or os.environ.get("S3_BUCKET")
    if not bucket:
        die("Set MODEL_S3_BUCKET or S3_BUCKET before using S3 operations.")
    return bucket


def s3_prefix() -> str:
    return os.environ.get("MODEL_S3_PREFIX") or os.environ.get("S3_PREFIX") or "comfyui"


def expand_s3_uri(value: str) -> str:
    if not value:
        return value
    bucket = os.environ.get("MODEL_S3_BUCKET") or os.environ.get("S3_BUCKET") or "${MODEL_S3_BUCKET}"
    prefix = os.environ.get("MODEL_S3_PREFIX") or os.environ.get("S3_PREFIX") or "comfyui"
    return (
        value.replace("${MODEL_S3_BUCKET}", bucket)
        .replace("$MODEL_S3_BUCKET", bucket)
        .replace("${S3_BUCKET}", bucket)
        .replace("$S3_BUCKET", bucket)
        .replace("${MODEL_S3_PREFIX}", prefix)
        .replace("$MODEL_S3_PREFIX", prefix)
        .replace("${S3_PREFIX}", prefix)
        .replace("$S3_PREFIX", prefix)
    )


def default_s3_uri_for(workspace_path: str) -> str:
    relative = workspace_path.replace("\\", "/").split("/workspace/models/", 1)[-1]
    return f"s3://${{MODEL_S3_BUCKET}}/${{MODEL_S3_PREFIX}}/models/{relative}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
