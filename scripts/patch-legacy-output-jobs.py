#!/usr/bin/env python3
"""Patch ComfyUI's jobs API to expose persistent output files as history.

The ComfyUI frontend's generated-image film strip is backed by /api/jobs, not
by /api/assets. Core ComfyUI stores job history in process memory, so a pod
restart loses the film strip even though /workspace/output and the asset DB are
persistent. This patch adds synthetic completed jobs for output files that are
present on disk but absent from in-memory history.
"""

from __future__ import annotations

import os
from pathlib import Path


COMFYUI_DIR = Path(os.environ.get("COMFYUI_DIR", "/opt/ComfyUI"))
JOBS_PATH = COMFYUI_DIR / "comfy_execution" / "jobs.py"
MARKER = "LEGACY_OUTPUT_JOBS_PATCH"


HELPER_CODE = r'''

# LEGACY_OUTPUT_JOBS_PATCH_START
import os as _legacy_os
import json as _legacy_json
import uuid as _legacy_uuid

import folder_paths as _legacy_folder_paths
from PIL import Image as _legacy_Image
from PIL import UnidentifiedImageError as _legacy_UnidentifiedImageError

_LEGACY_OUTPUT_NAMESPACE = _legacy_uuid.UUID("5a045ea2-7de1-4a08-bf52-2a8f4a7b4c71")
_LEGACY_IMAGE_EXTENSIONS = frozenset({".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"})
_LEGACY_VIDEO_EXTENSIONS = frozenset({".avi", ".mkv", ".mov", ".mp4", ".webm"})
_LEGACY_AUDIO_EXTENSIONS = frozenset({".flac", ".m4a", ".mp3", ".ogg", ".wav"})


def _legacy_media_type(filename: str) -> str | None:
    ext = _legacy_os.path.splitext(filename.lower())[1]
    if ext in _LEGACY_IMAGE_EXTENSIONS:
        return "images"
    if ext in _LEGACY_VIDEO_EXTENSIONS:
        return "video"
    if ext in _LEGACY_AUDIO_EXTENSIONS:
        return "audio"
    if ext in THREE_D_EXTENSIONS:
        return "3d"
    return None


def _legacy_output_key(item: dict) -> tuple[str, str, str] | None:
    filename = item.get("filename")
    if not filename:
        return None
    return (
        item.get("type", "output"),
        item.get("subfolder", "") or "",
        filename,
    )


def _legacy_history_output_keys(history: dict) -> set[tuple[str, str, str]]:
    keys: set[tuple[str, str, str]] = set()
    for history_item in history.values():
        outputs = history_item.get("outputs", {})
        if not isinstance(outputs, dict):
            continue
        for node_outputs in outputs.values():
            if not isinstance(node_outputs, dict):
                continue
            for items in node_outputs.values():
                if not isinstance(items, list):
                    continue
                for item in items:
                    if isinstance(item, dict):
                        key = _legacy_output_key(item)
                        if key is not None:
                            keys.add(key)
    return keys


def _legacy_output_item(abs_path: str, output_dir: str) -> tuple[str, dict, int] | None:
    filename = _legacy_os.path.basename(abs_path)
    media_type = _legacy_media_type(filename)
    if media_type is None:
        return None

    rel_dir = _legacy_os.path.relpath(_legacy_os.path.dirname(abs_path), output_dir)
    subfolder = "" if rel_dir == "." else rel_dir.replace(_legacy_os.sep, "/")
    stat = _legacy_os.stat(abs_path)
    item = {
        "filename": filename,
        "subfolder": subfolder,
        "type": "output",
    }
    if media_type == "3d":
        item["mediaType"] = "3d"
    return media_type, item, int(stat.st_mtime * 1000)


def _legacy_json_metadata(value, default=None):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return _legacy_json.loads(value)
        except Exception:
            return default
    return default


def _legacy_image_metadata(abs_path: str) -> tuple[dict, dict]:
    prompt = {}
    extra_pnginfo = {}

    try:
        with _legacy_Image.open(abs_path) as image:
            info = dict(image.info)
    except (_legacy_UnidentifiedImageError, OSError):
        return prompt, extra_pnginfo

    prompt = _legacy_json_metadata(info.get("prompt"), {}) or {}

    for key, value in info.items():
        if key == "prompt":
            continue
        parsed = _legacy_json_metadata(value)
        if parsed is not None:
            extra_pnginfo[key] = parsed

    return prompt, extra_pnginfo


def _legacy_file_workflow(abs_path: str, media_type: str, create_time: int) -> dict:
    prompt = {}
    extra_pnginfo = {}
    if media_type == "images":
        prompt, extra_pnginfo = _legacy_image_metadata(abs_path)

    extra_data = {"create_time": create_time}
    if extra_pnginfo:
        extra_data["extra_pnginfo"] = extra_pnginfo

    return {
        "prompt": prompt,
        "extra_data": extra_data,
    }


def _legacy_output_jobs(history: dict) -> list[dict]:
    output_dir = _legacy_folder_paths.get_output_directory()
    if not output_dir or not _legacy_os.path.isdir(output_dir):
        return []

    existing_keys = _legacy_history_output_keys(history)
    jobs: list[dict] = []
    for root, _, files in _legacy_os.walk(output_dir):
        for filename in files:
            abs_path = _legacy_os.path.join(root, filename)
            parsed = _legacy_output_item(abs_path, output_dir)
            if parsed is None:
                continue
            media_type, item, mtime_ms = parsed
            key = _legacy_output_key(item)
            if key in existing_keys:
                continue

            job_id = str(_legacy_uuid.uuid5(_LEGACY_OUTPUT_NAMESPACE, _legacy_os.path.abspath(abs_path)))
            preview_output = {
                **item,
                "nodeId": "legacy_output",
                "mediaType": media_type,
            }
            jobs.append({
                "id": job_id,
                "status": JobStatus.COMPLETED,
                "priority": -mtime_ms,
                "create_time": mtime_ms,
                "execution_start_time": mtime_ms,
                "execution_end_time": mtime_ms,
                "outputs_count": 1,
                "preview_output": preview_output,
            })
    return jobs


def _legacy_output_job_by_id(prompt_id: str, history: dict) -> Optional[dict]:
    for job in _legacy_output_jobs(history):
        if job["id"] == prompt_id:
            output = job["preview_output"]
            output_dir = _legacy_folder_paths.get_output_directory()
            abs_path = _legacy_os.path.join(output_dir, output.get("subfolder", "") or "", output["filename"])
            return {
                **job,
                "outputs": {
                    "legacy_output": {
                        output["mediaType"]: [
                            {
                                "filename": output["filename"],
                                "subfolder": output.get("subfolder", ""),
                                "type": "output",
                            }
                        ]
                    }
                },
                "execution_status": {"status_str": "success", "messages": []},
                "workflow": _legacy_file_workflow(abs_path, output["mediaType"], job["create_time"]),
            }
    return None
# LEGACY_OUTPUT_JOBS_PATCH_END
'''


def patch_jobs(source: str) -> str:
    if MARKER in source:
        return source

    source = source.replace(
        "from comfy_api.internal import prune_dict\n",
        "from comfy_api.internal import prune_dict\n" + HELPER_CODE,
        1,
    )

    source = source.replace(
        "    return None\n\n\ndef get_all_jobs(",
        "    legacy_job = _legacy_output_job_by_id(prompt_id, history)\n"
        "    if legacy_job is not None:\n"
        "        return legacy_job\n\n"
        "    return None\n\n\n"
        "def get_all_jobs(",
        1,
    )

    source = source.replace(
        "    if workflow_id:\n        jobs = [j for j in jobs if j.get('workflow_id') == workflow_id]\n",
        "    if JobStatus.COMPLETED in status_filter:\n"
        "        jobs.extend(_legacy_output_jobs(history))\n\n"
        "    if workflow_id:\n"
        "        jobs = [j for j in jobs if j.get('workflow_id') == workflow_id]\n",
        1,
    )

    if MARKER not in source:
        raise RuntimeError("Failed to patch comfy_execution/jobs.py")
    return source


def main() -> int:
    source = JOBS_PATH.read_text(encoding="utf-8")
    patched = patch_jobs(source)
    if patched == source:
        print(f"{JOBS_PATH} already patched")
        return 0
    JOBS_PATH.write_text(patched, encoding="utf-8")
    print(f"Patched {JOBS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
