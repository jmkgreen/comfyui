#!/usr/bin/env python3
"""Prepare ComfyUI workflow JSON for RunPod model-volume use."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


MODEL_EXTENSIONS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf")
DATE_TOKEN = "%date:yyyy-MM-dd%"
DEFAULT_FILENAME_PREFIX = f"{DATE_TOKEN}/ComfyUI"
SAVE_NODE_TYPES = {"SaveImage", "SaveAnimatedWEBP", "SaveWEBM"}


@dataclass(frozen=True)
class ResolvedModel:
    model_filename: str
    destination_path: str
    confidence: str


@dataclass
class Change:
    kind: str
    node_id: str
    node_type: str
    before: str
    after: str


class WorkflowPrepError(RuntimeError):
    pass


def looks_like_model(value: str) -> bool:
    return value.lower().endswith(MODEL_EXTENSIONS)


def model_reference(value: str) -> str:
    normalized = value.strip().replace("\\", "/").lstrip("/")
    if "/" in normalized:
        return normalized
    return Path(normalized).name


def replacement_for(observed_value: str, destination_path: str) -> str:
    normalized_destination = destination_path.strip().replace("\\", "/").lstrip("/")
    if "/" in observed_value.replace("\\", "/"):
        return normalized_destination
    return Path(normalized_destination).name


def node_type_from_stack(stack: list[tuple[str, Any]]) -> str:
    for _, value in reversed(stack):
        if isinstance(value, dict):
            for key in ("class_type", "type"):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    return candidate
            meta = value.get("_meta")
            if isinstance(meta, dict) and isinstance(meta.get("title"), str):
                return meta["title"]
    return ""


def node_id_from_stack(stack: list[tuple[str, Any]]) -> str:
    for _, value in reversed(stack):
        if isinstance(value, dict) and "id" in value:
            return str(value["id"])
    return ""


def in_node_model_catalog(stack: list[tuple[str, Any]]) -> bool:
    keys = [key for key, _ in stack]
    return "properties" in keys and "models" in keys


def read_resolved_manifest(path: Path, allowed_confidence: set[str]) -> dict[str, ResolvedModel]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"model_filename", "destination_path"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise WorkflowPrepError(f"{path} is missing required field(s): {', '.join(sorted(missing))}")

        resolved: dict[str, ResolvedModel] = {}
        for row in reader:
            model_filename = (row.get("model_filename") or "").strip()
            destination_path = (row.get("destination_path") or "").strip()
            confidence = (row.get("confidence") or "").strip().lower()
            if not model_filename or not destination_path:
                continue
            if allowed_confidence and confidence not in allowed_confidence:
                continue
            resolved[model_filename.replace("\\", "/").lstrip("/")] = ResolvedModel(
                model_filename=model_filename,
                destination_path=destination_path,
                confidence=confidence,
            )
        return resolved


def iter_model_strings(value: Any, stack: list[tuple[str, Any]]) -> Iterator[tuple[list[tuple[str, Any]], str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield from iter_model_strings(child, [*stack, (key, value)])
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from iter_model_strings(child, [*stack, (str(index), value)])
    elif isinstance(value, str) and looks_like_model(value) and not in_node_model_catalog(stack):
        yield stack, value


def update_model_references(workflow: Any, resolved: dict[str, ResolvedModel]) -> list[Change]:
    changes: list[Change] = []
    for stack, observed_value in iter_model_strings(workflow, []):
        reference = model_reference(observed_value)
        model = resolved.get(reference)
        if not model:
            continue

        replacement = replacement_for(observed_value, model.destination_path)
        if replacement == observed_value:
            continue

        key, container = stack[-1]
        if isinstance(container, dict):
            container[key] = replacement
        elif isinstance(container, list):
            container[int(key)] = replacement
        else:
            continue

        changes.append(
            Change(
                kind="model",
                node_id=node_id_from_stack(stack),
                node_type=node_type_from_stack(stack),
                before=observed_value,
                after=replacement,
            )
        )
    return changes


def collect_model_references(workflow: Any) -> set[str]:
    return {model_reference(value) for _, value in iter_model_strings(workflow, [])}


def has_date_pattern(value: str) -> bool:
    if re.search(r"%date:yyyy[-_/]MM[-_/]dd%", value, re.IGNORECASE):
        return True
    return bool(re.search(r"\d{4}-\d{2}-\d{2}", value))


def date_prefix_value(value: str, default_prefix: str) -> str:
    current = value.strip()
    if has_date_pattern(current):
        return value
    if not current:
        return default_prefix
    return f"{DATE_TOKEN}/{current}"


def widget_index_for(node: dict[str, Any], input_name: str) -> int | None:
    inputs = node.get("inputs")
    if not isinstance(inputs, list):
        return None

    widget_index = 0
    for input_info in inputs:
        if not isinstance(input_info, dict):
            continue
        widget = input_info.get("widget")
        if isinstance(widget, dict):
            if input_info.get("name") == input_name or widget.get("name") == input_name:
                return widget_index
            widget_index += 1
    return None


def save_prefix_widget_index(node: dict[str, Any]) -> int | None:
    index = widget_index_for(node, "filename_prefix")
    if index is not None:
        return index
    if str(node.get("type", "")) in SAVE_NODE_TYPES:
        return 0
    return None


def update_save_image_prefixes(workflow: Any, default_prefix: str) -> list[Change]:
    changes: list[Change] = []

    if not isinstance(workflow, dict):
        return changes

    nodes = workflow.get("nodes")
    if not isinstance(nodes, list):
        nodes = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        widgets = node.get("widgets_values")
        if not isinstance(widgets, list):
            continue
        index = save_prefix_widget_index(node)
        if index is None or index >= len(widgets) or not isinstance(widgets[index], str):
            continue
        before = widgets[index]
        after = date_prefix_value(before, default_prefix)
        if before == after:
            continue
        widgets[index] = after
        changes.append(
            Change(
                kind="filename_prefix",
                node_id=str(node.get("id", "")),
                node_type=str(node.get("type", "")),
                before=before,
                after=after,
            )
        )

    for node_id, node in workflow.items():
        if not isinstance(node, dict) or node.get("class_type") != "SaveImage":
            continue
        inputs = node.get("inputs")
        if not isinstance(inputs, dict) or not isinstance(inputs.get("filename_prefix"), str):
            continue
        before = inputs["filename_prefix"]
        after = date_prefix_value(before, default_prefix)
        if before == after:
            continue
        inputs["filename_prefix"] = after
        changes.append(
            Change(
                kind="filename_prefix",
                node_id=str(node_id),
                node_type=str(node.get("class_type", "")),
                before=before,
                after=after,
            )
        )
    return changes


def check_model_presence(
    models: list[ResolvedModel],
    models_root: Path | None,
    require_present: bool,
) -> list[str]:
    if models_root is None:
        return []

    missing = []
    for model in models:
        model_path = models_root / model.destination_path
        if not model_path.exists():
            missing.append(model.destination_path)

    if missing and require_present:
        sample = "\n".join(f"  - {path}" for path in missing[:20])
        remainder = "" if len(missing) <= 20 else f"\n  ... and {len(missing) - 20} more"
        raise WorkflowPrepError(f"Missing model file(s) under {models_root}:\n{sample}{remainder}")
    return missing


def output_path_for(workflow_path: Path, output: Path | None, in_place: bool) -> Path:
    if in_place:
        return workflow_path
    if output:
        return output
    return workflow_path.with_name(f"{workflow_path.stem}.prepared{workflow_path.suffix}")


def prepare_workflow(args: argparse.Namespace) -> int:
    allowed_confidence = {value.lower() for value in args.confidence}
    resolved = read_resolved_manifest(args.manifest, allowed_confidence)

    if args.output and len(args.workflows) != 1:
        raise WorkflowPrepError("--output can only be used with one workflow")

    exit_code = 0
    for workflow_path in args.workflows:
        with workflow_path.open("r", encoding="utf-8") as handle:
            original = json.load(handle)
        workflow = deepcopy(original)
        referenced = collect_model_references(workflow)
        referenced_models = [model for key, model in resolved.items() if key in referenced]
        missing = check_model_presence(
            referenced_models,
            args.models_root,
            require_present=not args.allow_missing,
        )

        changes = []
        changes.extend(update_model_references(workflow, resolved))
        changes.extend(update_save_image_prefixes(workflow, args.default_filename_prefix))

        destination = output_path_for(workflow_path, args.output, args.in_place)
        should_write = workflow != original or destination != workflow_path
        if should_write and not args.dry_run:
            destination.write_text(json.dumps(workflow, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        if workflow == original and destination == workflow_path:
            print(f"{workflow_path}: already prepared")
        elif args.dry_run:
            print(f"{workflow_path}: would write {destination}")
        else:
            print(f"{workflow_path}: wrote {destination}")

        for change in changes:
            node = f" node={change.node_id}" if change.node_id else ""
            print(f"  {change.kind}{node}: {change.before!r} -> {change.after!r}")

        if missing:
            print(f"  warning: {len(missing)} manifest model(s) are missing under {args.models_root}")
            if not args.allow_missing:
                exit_code = 1

    return exit_code


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rewrite reviewed model references in ComfyUI workflow JSON and ensure SaveImage "
            "filename prefixes include a YYYY-MM-DD date token."
        )
    )
    parser.add_argument("workflows", type=Path, nargs="+", help="ComfyUI workflow JSON file(s) to prepare.")
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Reviewed resolved-models.csv from comfyui-s3-model-volume-tools.",
    )
    parser.add_argument(
        "--models-root",
        type=Path,
        help="Optional local or mounted /workspace/models root to check for destination_path files.",
    )
    parser.add_argument("--output", type=Path, help="Output JSON path. Only valid with one workflow.")
    parser.add_argument("--in-place", action="store_true", help="Rewrite workflow file in place.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing.")
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Do not fail when --models-root is provided and manifest models are missing.",
    )
    parser.add_argument(
        "--confidence",
        action="append",
        default=["high", "medium"],
        help="Manifest confidence level to apply. May be repeated. Defaults to high and medium.",
    )
    parser.add_argument(
        "--default-filename-prefix",
        default=DEFAULT_FILENAME_PREFIX,
        help=f"Prefix used when SaveImage has an empty filename_prefix. Defaults to {DEFAULT_FILENAME_PREFIX!r}.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        return prepare_workflow(args)
    except (OSError, json.JSONDecodeError, WorkflowPrepError) as exc:
        print(f"prepare-workflow: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
