# ComfyUI on RunPod

Docker image and helper scripts for running ComfyUI on RunPod with:

- ComfyUI and Python dependencies baked into the image.
- RunPod network storage mounted at `/workspace` for models, outputs, inputs, workflows, config, and user data.
- S3 as the long-term source of truth for models and optional backup target for generations.

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
S3_BUCKET=your-bucket-name
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=...
```

Optional environment variables:

```text
S3_PREFIX=comfyui
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

## Model Restore

Edit `/workspace/config/essential-models.txt` or this repo's `config/essential-models.txt`:

```text
models/checkpoints/example.safetensors checkpoints/example.safetensors
models/vae/example_vae.safetensors vae/example_vae.safetensors
```

Then run:

```bash
S3_BUCKET=my-bucket /opt/scripts/ensure-models.sh
```

With the default `S3_PREFIX=comfyui`, the first column is resolved under `s3://my-bucket/comfyui/`, and the second column is resolved under `/workspace/models/`.

## Sync One Model

```bash
S3_BUCKET=my-bucket /opt/scripts/sync-model-from-s3.sh \
  models/checkpoints/new-model.safetensors \
  checkpoints/new-model.safetensors
```

For prefixes, end the S3 path with `/`:

```bash
S3_BUCKET=my-bucket /opt/scripts/sync-model-from-s3.sh \
  models/controlnet/ \
  controlnet
```

## Push Generations

```bash
S3_BUCKET=my-bucket /opt/scripts/push-generations-to-s3.sh
```

By default this writes to:

```text
s3://my-bucket/comfyui/generations/YYYY-MM-DD/HHMMSS/
```

Set `RUN_LABEL=my-session` to choose the final folder name.

## Open Questions

1. What is the canonical repository URL for `ComfyUI-RunpodDirect`?
2. Should the model manifest grow checksum support before you rely on it heavily?
