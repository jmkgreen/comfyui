#!/usr/bin/env python3
"""Resolve desired ComfyUI model filenames into a reviewable CSV.

Hugging Face search uses HF_TOKEN. If --search-huggingface is requested without
HF_TOKEN, the script warns and falls back to registry/path inference.

CivitAI search uses CIVITAI_TOKEN. If CivitAI is disabled or no token is
available, the script warns when unresolved models would otherwise need it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from model_resolver_lib import (  # noqa: E402
    CSV_FIELDS,
    default_s3_uri_for,
    infer_workspace_path,
    load_path_rules,
    load_source_policy,
    mirror_policy_for,
    normalize_row,
    read_model_filenames,
    read_registry,
    token_env_for,
    warn,
    write_rows,
)


def request_json(url: str, headers: Dict[str, str], timeout: int = 20):
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def hf_file_url(repo_id: str, filename: str) -> str:
    quoted_repo = "/".join(urllib.parse.quote(part) for part in repo_id.split("/"))
    return f"https://huggingface.co/{quoted_repo}/resolve/main/{urllib.parse.quote(filename)}"


def search_huggingface(filename: str, token: str) -> Optional[Dict[str, str]]:
    query = urllib.parse.urlencode({"search": filename, "full": "true", "limit": "15"})
    url = f"https://huggingface.co/api/models?{query}"
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "comfyui-model-resolver/1"}
    try:
        results = request_json(url, headers)
    except Exception as exc:  # noqa: BLE001
        warn(f"Hugging Face search failed for {filename}: {exc}")
        return None

    matches: List[Dict[str, str]] = []
    for model in results if isinstance(results, list) else []:
        repo_id = model.get("modelId") or model.get("id")
        siblings = model.get("siblings") or []
        for sibling in siblings:
            rfilename = sibling.get("rfilename") if isinstance(sibling, dict) else None
            if rfilename and Path(rfilename).name == filename and repo_id:
                matches.append(
                    {
                        "repo_id": repo_id,
                        "canonical_url": hf_file_url(repo_id, rfilename),
                        "source_type": "huggingface_public",
                    }
                )

    unique = {match["canonical_url"]: match for match in matches}
    if len(unique) == 1:
        return next(iter(unique.values()))
    if len(unique) > 1:
        warn(f"Hugging Face returned multiple exact file matches for {filename}; marking low confidence.")
        return {
            "canonical_url": "",
            "source_type": "huggingface_public",
            "notes": "Multiple Hugging Face repositories contain this filename; review manually.",
        }
    return None


def search_civitai(filename: str, token: str) -> Optional[Dict[str, str]]:
    query = urllib.parse.urlencode({"query": filename, "limit": "10"})
    url = f"https://civitai.com/api/v1/models?{query}"
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "comfyui-model-resolver/1"}
    try:
        results = request_json(url, headers)
    except Exception as exc:  # noqa: BLE001
        warn(f"CivitAI search failed for {filename}: {exc}")
        return None

    matches: List[Dict[str, str]] = []
    for item in results.get("items", []) if isinstance(results, dict) else []:
        for version in item.get("modelVersions", []) or []:
            version_id = version.get("id")
            for file_info in version.get("files", []) or []:
                name = file_info.get("name")
                if name == filename and version_id:
                    matches.append(
                        {
                            "canonical_url": f"https://civitai.com/api/download/models/{version_id}",
                            "source_type": "civitai_gated",
                        }
                    )

    unique = {match["canonical_url"]: match for match in matches}
    if len(unique) == 1:
        return next(iter(unique.values()))
    if len(unique) > 1:
        warn(f"CivitAI returned multiple exact file matches for {filename}; marking low confidence.")
        return {
            "canonical_url": "",
            "source_type": "civitai_gated",
            "notes": "Multiple CivitAI model versions contain this filename; review manually.",
        }
    return None


def bool_flag(parser: argparse.ArgumentParser, name: str, default: Optional[bool], help_text: str):
    group = parser.add_mutually_exclusive_group()
    group.add_argument(f"--{name}", dest=name.replace("-", "_"), action="store_true", help=help_text)
    group.add_argument(f"--no-{name}", dest=name.replace("-", "_"), action="store_false")
    parser.set_defaults(**{name.replace("-", "_"): default})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="config/essential-models.txt", type=Path)
    parser.add_argument("--registry", default="config/model_registry.csv", type=Path)
    parser.add_argument("--rules", default="config/model_path_rules.yaml", type=Path)
    parser.add_argument("--source-policy", default="config/source_policy.yaml", type=Path)
    parser.add_argument("--output", default="models.resolved.csv", type=Path)
    parser.add_argument("--models-root", default="/workspace/models")
    bool_flag(parser, "search-huggingface", None, "Search Hugging Face when HF_TOKEN is set.")
    bool_flag(parser, "enable-civitai", None, "Search CivitAI when CIVITAI_TOKEN is set.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = read_registry(args.registry)
    rules = load_path_rules(args.rules)
    policies = load_source_policy(args.source_policy)
    filenames = read_model_filenames(args.input)

    hf_token = os.environ.get("HF_TOKEN")
    civitai_token = os.environ.get("CIVITAI_TOKEN")
    search_hf = bool(hf_token) if args.search_huggingface is None else args.search_huggingface
    search_civ = bool(civitai_token) if args.enable_civitai is None else args.enable_civitai

    if args.search_huggingface and not hf_token:
        warn("--search-huggingface was requested but HF_TOKEN is not set; using registry/path inference only.")
        search_hf = False
    if args.enable_civitai and not civitai_token:
        warn("--enable-civitai was requested but CIVITAI_TOKEN is not set; CivitAI search will be skipped.")
        search_civ = False
    if not search_hf and hf_token:
        warn("Hugging Face search is disabled even though HF_TOKEN is set.")
    if not search_civ:
        reason = "CIVITAI_TOKEN is not set" if not civitai_token else "CivitAI search was disabled by flag"
        warn(f"CivitAI search is disabled: {reason}.")

    rows: List[Dict[str, str]] = []
    for filename in filenames:
        if filename in registry:
            row = normalize_row(registry[filename])
            row["confidence"] = row.get("confidence") or "high"
            row["notes"] = row.get("notes") or "Registry exact match."
            rows.append(row)
            continue

        workspace_path = infer_workspace_path(filename, rules, args.models_root)
        found: Optional[Dict[str, str]] = None
        notes: List[str] = []

        if search_hf and hf_token:
            found = search_huggingface(filename, hf_token)
        elif args.search_huggingface:
            notes.append("Hugging Face search requested but HF_TOKEN was missing.")

        if not found:
            if search_civ and civitai_token:
                found = search_civitai(filename, civitai_token)
            else:
                notes.append("CivitAI search skipped because CIVITAI_TOKEN was missing or search was disabled.")

        if found and found.get("canonical_url"):
            source_type = found["source_type"]
            row = {
                "model_filename": filename,
                "canonical_url": found["canonical_url"],
                "workspace_path": workspace_path,
                "source_type": source_type,
                "mirror_policy": mirror_policy_for(source_type, policies),
                "s3_uri": "",
                "sha256": "",
                "confidence": "high",
                "notes": found.get("notes", ""),
            }
            if row["mirror_policy"] != "never":
                row["s3_uri"] = default_s3_uri_for(workspace_path)
            rows.append(row)
            continue

        source_type = found.get("source_type") if found else ""
        notes.extend([found.get("notes", "")] if found and found.get("notes") else [])
        if source_type and token_env_for(source_type, policies):
            notes.append(f"Requires {token_env_for(source_type, policies)} at download time.")
        rows.append(
            {
                "model_filename": filename,
                "canonical_url": "",
                "workspace_path": workspace_path,
                "source_type": source_type,
                "mirror_policy": mirror_policy_for(source_type, policies) if source_type else "optional",
                "s3_uri": default_s3_uri_for(workspace_path) if source_type else "",
                "sha256": "",
                "confidence": "low",
                "notes": " ".join(note for note in notes if note) or "No registry or exact public source match found.",
            }
        )

    write_rows(args.output, rows)
    print(f"Wrote {len(rows)} row(s) to {args.output}")
    print(f"Columns: {', '.join(CSV_FIELDS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
