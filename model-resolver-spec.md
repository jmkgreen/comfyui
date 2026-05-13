# ComfyUI Model Resolver Specification

## Purpose

Build a small set of scripts for a RunPod-hosted ComfyUI image that can turn a list of desired model filenames into a reviewed CSV containing:

```csv
Model filename,URL to download,path within /workspace/models to download to
```

The resolver should help maintain model availability on RunPod network storage while avoiding unnecessary duplication of files that already have stable public canonical sources.

## Background

ComfyUI workflow files often reference model files by filename only. Those filenames usually match the author's local filename at workflow creation time and may not directly identify:

- the original download URL,
- the correct ComfyUI model subdirectory,
- whether the source is public, gated, authenticated, or fragile,
- whether the model should be mirrored to S3.

The tool should therefore be a best-effort resolver with a manual review step, not a fully automatic trusted downloader.

## Core Principle

S3 is not the universal source of truth for every model.

Use the original public source as the canonical source when it is stable and publicly available. Use S3 primarily for private, gated, paid, fragile, manually acquired, or at-risk model files.

## Source Policy

### Public canonical sources

Examples:

- Hugging Face public model repositories
- GitHub releases
- other stable public model hosting sources

Policy:

- Do not mirror these files to S3 by default.
- Do not prefer S3 for downloads when the public canonical URL is available.
- Store the canonical public URL in the generated CSV.
- Allow optional local caching on `/workspace/models` only.
- If the file is missing from `/workspace/models`, download it from the original public source.

Rationale:

- Avoid paying to store large public files unnecessarily.
- Avoid stale mirrored copies.
- Preserve clear provenance.
- Make updates and licence tracking easier.

### Gated, authenticated, fragile, or manually acquired sources

Examples:

- CivitAI LoRAs or checkpoints requiring an API token
- gated Hugging Face repositories
- private model downloads
- files distributed via temporary links
- files that may be removed, renamed, or rate-limited

Policy:

- These may be mirrored to S3 after download.
- S3 can become the preferred restore source once a file has been mirrored.
- The original URL and source metadata should still be retained.
- Authentication tokens must never be written into generated CSV files, logs, or committed config.
- Download scripts should read tokens from environment variables.

Rationale:

- Gated sources may disappear or become difficult to re-download.
- The user may have a legitimate copy and wants resilience.
- S3 provides a controlled backup and faster restore path.

## Desired Files

```text
scripts/
  resolve_models.py
  ensure_models.py
  mirror_model_to_s3.py
  sync_generations_to_s3.sh

config/
  model_registry.csv
  model_path_rules.yaml
  essential-models.txt
  source_policy.yaml
```

## Implementation Decisions

- Use the repo's existing hyphenated model list convention: `config/essential-models.txt`.
- Avoid adding PyYAML for now. The resolver scripts should parse the small YAML config files with narrow built-in parsers that support the documented shapes only.
- Hugging Face search should run at resolve time when `HF_TOKEN` is set. If `--search-huggingface` is explicitly selected without `HF_TOKEN`, the resolver should warn clearly and fall back to registry/path inference only.
- CivitAI search should run when needed if `CIVITAI_TOKEN` is set. If CivitAI search is disabled or unavailable, the resolver should log why it was skipped.
- Switch cleanly to `scripts/ensure_models.py` and remove the old `scripts/ensure-models.sh` path to avoid two competing restore flows.
- S3 bucket and prefix should be supplied by environment variables. Bucket is required and missing bucket configuration should be a hard error; prefix should default to `comfyui`.
- S3 environment placeholders and defaults should be documented in both the README and the relevant script headers.

## Input Files

### `config/essential-models.txt`

One model filename per line.

Example:

```text
flux1-dev.safetensors
t5xxl_fp16.safetensors
a-detailer-lora.safetensors
```

Blank lines and lines beginning with `#` should be ignored.

### `config/model_registry.csv`

A manually curated override registry.

Recommended columns:

```csv
model_filename,canonical_url,workspace_path,source_type,mirror_policy,s3_uri,sha256,notes
```

Example:

```csv
flux1-dev.safetensors,https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors,/workspace/models/unet/flux1-dev.safetensors,huggingface_public,never,,,
my-private-lora.safetensors,https://civitai.com/api/download/models/123456,/workspace/models/loras/my-private-lora.safetensors,civitai_gated,mirror_after_download,s3://my-bucket/comfyui/models/loras/my-private-lora.safetensors,,Requires CIVITAI_TOKEN
```

### `config/source_policy.yaml`

Defines default behaviour by source type.

Example:

```yaml
sources:
  huggingface_public:
    canonical: public_url
    mirror_to_s3: false
    prefer_s3_restore: false
    token_env: null

  huggingface_gated:
    canonical: public_url
    mirror_to_s3: true
    prefer_s3_restore: true
    token_env: HF_TOKEN

  civitai_public:
    canonical: public_url
    mirror_to_s3: false
    prefer_s3_restore: false
    token_env: null

  civitai_gated:
    canonical: public_url
    mirror_to_s3: true
    prefer_s3_restore: true
    token_env: CIVITAI_TOKEN

  manual_private:
    canonical: s3
    mirror_to_s3: true
    prefer_s3_restore: true
    token_env: null
```

## Generated CSV

The resolver should output a reviewable CSV.

Minimum columns:

```csv
Model filename,URL to download,path within /workspace/models to download to
```

Recommended columns:

```csv
model_filename,canonical_url,workspace_path,source_type,mirror_policy,s3_uri,confidence,notes
```

Where:

- `canonical_url` is the preferred original source URL where appropriate.
- `workspace_path` is the final full path under `/workspace/models`.
- `source_type` is one of the known source policy types.
- `mirror_policy` should be one of:
  - `never`
  - `optional`
  - `mirror_after_download`
  - `s3_primary`
- `s3_uri` is only required when S3 is the primary or mirror destination.
- `confidence` should be `high`, `medium`, or `low`.
- `notes` should explain ambiguity or required tokens.

## Script: `resolve_models.py`

### Purpose

Given a list of wanted filenames, generate a candidate model table.

### Example

```bash
python scripts/resolve_models.py \
  --input config/essential-models.txt \
  --registry config/model_registry.csv \
  --rules config/model_path_rules.yaml \
  --source-policy config/source_policy.yaml \
  --output models.resolved.csv
```

### Resolution order

1. Check `model_registry.csv` for an exact filename match.
2. Search known public sources, starting with Hugging Face.
3. Optionally search CivitAI if enabled and a token is available.
4. Infer the ComfyUI destination path using filename and source metadata.
5. Emit a candidate row with confidence and notes.

### Safety requirements

- Do not include authentication tokens in output.
- Do not auto-classify gated/authenticated files as public.
- Do not silently choose between multiple equally plausible candidates.
- Mark ambiguous matches as `low` confidence.
- Prefer exact filename matches over fuzzy matches.
- Do not recommend S3 mirroring for public Hugging Face files unless explicitly configured.

## Script: `ensure_models.py`

### Purpose

Ensure all models listed in a reviewed CSV exist in `/workspace/models`.

### Example

```bash
python scripts/ensure_models.py \
  --manifest models.resolved.csv \
  --models-root /workspace/models
```

### Behaviour

For each model:

1. If the file exists at `workspace_path`, skip it.
2. If `prefer_s3_restore` is true and `s3_uri` exists, restore from S3 first.
3. Otherwise download from `canonical_url`.
4. If source requires a token, read it from the configured environment variable.
5. If `mirror_policy` is `mirror_after_download`, upload the downloaded file to S3 after successful download.
6. Optionally verify `sha256` if present.

### Token handling

Supported environment variables should include:

```bash
HF_TOKEN
CIVITAI_TOKEN
AWS_PROFILE
AWS_REGION
```

Tokens must be passed in headers or query parameters only at runtime. They must not be persisted into CSV, logs, shell history, or generated files.

## Script: `mirror_model_to_s3.py`

### Purpose

Manually mirror a local model file to S3 and optionally emit/update a registry row.

### Example

```bash
python scripts/mirror_model_to_s3.py \
  --file /workspace/models/loras/my-private-lora.safetensors \
  --s3-uri s3://my-bucket/comfyui/models/loras/my-private-lora.safetensors \
  --source-url https://civitai.com/api/download/models/123456 \
  --source-type civitai_gated
```

### Behaviour

- Upload the file to S3.
- Calculate SHA-256.
- Print a suggested `model_registry.csv` row.
- Never upload without explicit user command.

## Script: `sync_generations_to_s3.sh`

### Purpose

At user discretion, sync generated outputs from RunPod network storage to a date-based S3 prefix.

### Example

```bash
scripts/sync_generations_to_s3.sh s3://my-bucket/comfyui/generations
```

Expected destination:

```text
s3://my-bucket/comfyui/generations/YYYY-MM-DD/
```

The script should sync from:

```text
/workspace/output/
```

## ComfyUI Path Inference

Default path rules should be configurable in `model_path_rules.yaml`.

Suggested defaults:

```yaml
rules:
  - match: "*vae*"
    path: "vae"
  - match: "*lora*"
    path: "loras"
  - match: "*controlnet*"
    path: "controlnet"
  - match: "*clip*"
    path: "clip"
  - match: "t5xxl*"
    path: "clip"
  - match: "*unet*"
    path: "unet"
  - match: "flux1-*.safetensors"
    path: "unet"
  - match: "*.safetensors"
    path: "checkpoints"
  - match: "*.ckpt"
    path: "checkpoints"
```

The resolved `workspace_path` should always be a full path, for example:

```text
/workspace/models/loras/example.safetensors
```

## S3 Model Storage Layout

Suggested layout:

```text
s3://<bucket>/comfyui/models/checkpoints/
s3://<bucket>/comfyui/models/unet/
s3://<bucket>/comfyui/models/clip/
s3://<bucket>/comfyui/models/vae/
s3://<bucket>/comfyui/models/loras/
s3://<bucket>/comfyui/models/controlnet/
s3://<bucket>/comfyui/generations/YYYY-MM-DD/
```

Only mirrored/private/gated/fragile models should normally be stored under `comfyui/models/`.

## Acceptance Criteria

- Given a filename already in `model_registry.csv`, the resolver emits the exact registered row.
- Given a public Hugging Face model, the resolver emits the Hugging Face URL and `mirror_policy=never` by default.
- Given a CivitAI gated model, the resolver marks it as token-required and `mirror_policy=mirror_after_download` when configured.
- `ensure_models.py` does not download a file that already exists locally.
- `ensure_models.py` restores from S3 first only when policy says S3 is preferred.
- Authentication tokens never appear in generated CSV output or logs.
- The generation sync script creates a date-based S3 prefix.
- All scripts support `--dry-run` where meaningful.
- All destructive behaviour requires an explicit flag.

## Non-Goals

- Perfectly resolving every arbitrary model filename.
- Scraping websites in brittle ways.
- Circumventing licence gates or authentication requirements.
- Automatically mirroring all public models to S3.
- Automatically installing ComfyUI custom nodes.

## Recommended Workflow

1. Add wanted model filenames to `config/essential-models.txt`.
2. Run `resolve_models.py`.
3. Review the generated CSV.
4. Manually fix low-confidence rows.
5. Add verified rows to `model_registry.csv`.
6. Run `ensure_models.py` on RunPod.
7. For gated or fragile models, mirror to S3 after successful download.
8. Periodically sync generations to S3 using `sync_generations_to_s3.sh`.
