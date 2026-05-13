# ComfyUI on RunPod

Docker image and helper scripts for running ComfyUI on RunPod with:

- ComfyUI and Python dependencies baked into the image.
- RunPod network storage mounted at `/workspace` for models, outputs, inputs, workflows, config, and user data.
- Public canonical model URLs where available, with S3 reserved for private, gated, fragile, or manually mirrored models.
- Optional S3 backup target for generations.

Large model files are intentionally not stored in this repository or Docker image.

## Image Layout

Image-local paths:

```text
/opt/ComfyUI
/opt/venv
/opt/scripts
```

Persistent RunPod paths:

```text
/workspace/models
/workspace/input
/workspace/output
/workspace/user
/workspace/workflows
/workspace/custom_nodes_experimental
/workspace/config
```

At startup, `/opt/ComfyUI/models` is linked to `/workspace/models`, `/opt/ComfyUI/user` is linked to `/workspace/user`, and ComfyUI is started with `/workspace/input`, `/workspace/output`, and `/workspace/user`.

Jupyter Lab is also installed and starts on port `8888` by default, rooted at `/workspace`.

## Build

```bash
docker build -t comfyui-runpod .
```

Useful build arguments:

```bash
docker build \
  --build-arg COMFYUI_REF=master \
  --build-arg COMFYUI_MANAGER_REF=main \
  -t comfyui-runpod .
```

ComfyUI core currently uses `master` as its upstream default branch. The stable custom nodes in `config/stable-custom-nodes.txt` use `main`/default branches for early iteration.

For a more reproducible image, set `COMFYUI_REF`, `COMFYUI_MANAGER_REF`, and custom node refs to commit SHAs instead of branches.

## Stable Custom Nodes

The image bakes in the custom nodes listed in:

```text
config/stable-custom-nodes.txt
```

Current starter set:

- `ComfyUI_essentials`
- `ComfyUI-Easy-Use`
- `ComfyUI-Impact-Pack`
- `ComfyUI-Impact-Subpack`
- `ComfyUI-KJNodes`
- `ComfyUI-WanVideoWrapper`
- `rgthree-comfy`
- `seedvr2_videoupscaler`

`ComfyUI-RunpodDirect` is listed as a TODO until its canonical repository URL is confirmed.

## RunPod Environment

Minimum environment variables:

```text
MODEL_S3_BUCKET=your-bucket-name
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=...
```

Optional environment variables:

```text
MODEL_S3_PREFIX=comfyui
S3_BUCKET=your-bucket-name
S3_PREFIX=comfyui
HF_TOKEN=
CIVITAI_TOKEN=
AWS_PROFILE=
AWS_REGION=
COMFYUI_PORT=8188
EXTRA_COMFYUI_ARGS=
ENABLE_EXPERIMENTAL_CUSTOM_NODES=1
JUPYTER_ENABLE=1
JUPYTER_PORT=8888
JUPYTER_ROOT_DIR=/workspace
JUPYTER_TOKEN=
JUPYTER_ALLOW_ORIGIN=*
JUPYTER_TRUST_XHEADERS=1
```

RunPod should expose port `8188` over HTTP for ComfyUI and port `8888` over HTTP for Jupyter Lab.

If `JUPYTER_TOKEN` is unset, Jupyter uses its normal generated token and prints the access URL in the container logs. Set `JUPYTER_TOKEN` to a known value if you want predictable access through the RunPod web console.

RunPod proxies Jupyter through a public hostname while the container sees an internal host and port. `JUPYTER_ALLOW_ORIGIN=*` and `JUPYTER_TRUST_XHEADERS=1` are enabled by default so Jupyter accepts the proxied login flow. Keep Jupyter token-protected when exposing port `8888`.

The image runs `tini -s` as the entrypoint so child processes are reaped even if the container platform wraps the process tree. ComfyUI's image-local `user` path is also symlinked into `/workspace/user` because recent ComfyUI database initialization may still expect a writable `user` directory under the install path.

`MODEL_S3_BUCKET` is the preferred bucket environment variable for model resolver scripts. `S3_BUCKET` remains accepted as a compatibility alias. `MODEL_S3_PREFIX` defaults to `comfyui` when unset.

## Model Resolution

Edit `/workspace/config/essential-models.txt` or this repo's `config/essential-models.txt` with one desired model filename per line. Blank lines and comments are ignored.

Generate a reviewable CSV:

```bash
HF_TOKEN=... python /opt/scripts/resolve_models.py \
  --input /workspace/config/essential-models.txt \
  --registry /workspace/config/model_registry.csv \
  --rules /workspace/config/model_path_rules.yaml \
  --source-policy /workspace/config/source_policy.yaml \
  --output /workspace/config/models.resolved.csv
```

If `HF_TOKEN` is set, Hugging Face is searched at resolve time. If `--search-huggingface` is passed without `HF_TOKEN`, the resolver warns and falls back to registry/path inference. CivitAI search runs when needed if `CIVITAI_TOKEN` is set; otherwise the resolver logs why it was skipped.

Review the generated CSV before download. Public Hugging Face files should normally keep their canonical Hugging Face URL and `mirror_policy=never`. Private, gated, fragile, or manually acquired files can use S3 placeholders such as:

```text
s3://${MODEL_S3_BUCKET}/${MODEL_S3_PREFIX}/models/loras/example.safetensors
```

Ensure reviewed models exist under `/workspace/models`:

```bash
MODEL_S3_BUCKET=my-bucket python /opt/scripts/ensure_models.py \
  --manifest /workspace/config/models.resolved.csv \
  --models-root /workspace/models
```

`ensure_models.py` skips files that already exist, restores from S3 first only when the source policy prefers S3, otherwise downloads from `canonical_url`, and verifies `sha256` when present. Pass `--dry-run` to preview actions. Pass `--mirror-after-download` to allow rows marked `mirror_after_download` to upload after a successful download.

## Sync One Model

```bash
MODEL_S3_BUCKET=my-bucket /opt/scripts/sync-model-from-s3.sh \
  models/checkpoints/new-model.safetensors \
  checkpoints/new-model.safetensors
```

For prefixes, end the S3 path with `/`:

```bash
MODEL_S3_BUCKET=my-bucket /opt/scripts/sync-model-from-s3.sh \
  models/controlnet/ \
  controlnet
```

To manually mirror a local model and print a suggested registry row:

```bash
MODEL_S3_BUCKET=my-bucket python /opt/scripts/mirror_model_to_s3.py \
  --file /workspace/models/loras/my-private-lora.safetensors \
  --s3-uri 's3://${MODEL_S3_BUCKET}/${MODEL_S3_PREFIX}/models/loras/my-private-lora.safetensors' \
  --source-url https://civitai.com/api/download/models/123456 \
  --source-type civitai_gated
```

## Push Generations

```bash
MODEL_S3_BUCKET=my-bucket /opt/scripts/sync_generations_to_s3.sh
```

By default this writes to:

```text
s3://my-bucket/comfyui/generations/YYYY-MM-DD/
```

You can also pass an explicit base destination:

```bash
MODEL_S3_BUCKET=my-bucket /opt/scripts/sync_generations_to_s3.sh s3://my-bucket/comfyui/generations
```

## Open Questions

1. What is the canonical repository URL for `ComfyUI-RunpodDirect`?
2. Should the model manifest grow checksum support before you rely on it heavily?
