# ComfyUI on RunPod

Docker image and helper scripts for running ComfyUI on RunPod with:

- ComfyUI and Python dependencies baked into the image.
- SageAttention installed in the image and auto-enabled when available.
- RunPod network storage mounted at `/workspace` for models, outputs, inputs, workflows, config, and user data.
- A runtime that consumes a prepared `/workspace/models` directory.

Large model files are intentionally not stored in this repository or Docker image.

Model discovery, source resolution, and RunPod network-volume population are handled by the standalone adjacent project:

```text
../comfyui-s3-model-volume-tools
```

That tool can be run from a local PC, VM, or CI runner against the RunPod network volume's S3-compatible API, so a GPU pod does not need to be running just to prepare or repair model storage.

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
  --build-arg INSTALL_SAGEATTENTION=1 \
  --build-arg SAGEATTENTION_WHEEL_URL=https://github.com/Comfy-Org/wheels/releases/download/sageattention-latest/sageattention-2.2.0%2Bcu128torch2.10-cp312-cp312-manylinux_2_34_x86_64.manylinux_2_35_x86_64.whl \
  --build-arg ONNXRUNTIME_CUDA12_INDEX=https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/ \
  -t comfyui-runpod .
```

ComfyUI core currently uses `master` as its upstream default branch. The stable custom nodes in `config/stable-custom-nodes.txt` use `main`/default branches for early iteration.

The default base image uses PyTorch 2.10 with CUDA 12.8 and Python 3.12. SageAttention is installed from a prebuilt Comfy wheel instead of compiling during the Docker build. The wheel is installed after stable custom-node requirements so the Docker build fails if a later dependency changes PyTorch to an incompatible version. If SageAttention is not wanted for a smaller image or for a GPU stack where it is not compatible, build with `--build-arg INSTALL_SAGEATTENTION=0`.

The venv uses system site packages so it can share the PyTorch stack from the base image. The Dockerfile explicitly installs a matched Requests/urllib3/charset-normalizer/chardet stack into the venv to avoid importing an incompatible mix from the base and venv layers.

The Dockerfile also constrains `torch`, `torchvision`, and `torchaudio` to the PyTorch 2.10 image line because the default SageAttention wheel is compiled for CUDA 12.8 and Torch 2.10. The build validates the Torch version immediately before installing SageAttention so dependency drift fails with a clear error.

For a more reproducible image, set `COMFYUI_REF`, `COMFYUI_MANAGER_REF`, custom node refs, and performance package versions to known-good values instead of floating branches or defaults.

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
- `cg-use-everywhere`
- `seedvr2_videoupscaler`
- `comfyui-vrgamedevgirl`
- `RES4LYF`
- `ComfyUI-Crystools`
- `ComfyUI_IPAdapter_plus`
- `comfyui_controlnet_aux`
- `ComfyUI-3D-Pack`
- `ComfyUI-GGUF`
- `ComfyUI-LTXVideo`

`ComfyUI-RunpodDirect` is listed as a TODO until its canonical repository URL is confirmed.

Stable node install notes:

- `comfyui_controlnet_aux` installs `onnxruntime-gpu`; CUDA 12 builds use `ONNXRUNTIME_CUDA12_INDEX`.
- `ComfyUI-3D-Pack` runs its `install.py` during image build and needs compiler/CMake tooling for its prebuilt package selection and runtime JIT extension support.
- `ComfyUI-3D-Pack` currently pulls `gpytoolbox`, which may still contain removed NumPy 2 aliases such as `np.Inf`; the image applies `scripts/patch-numpy2-compat.py` after custom-node installation instead of pinning all of NumPy below 2.0.
- `ComfyUI-3D-Pack` mesh tooling can load PyMeshlab plugins that need `libOpenGL.so.0`; the image installs `libopengl0` in addition to `libgl1`.
- `ComfyUI_IPAdapter_plus`, `ComfyUI-3D-Pack`, `ComfyUI-GGUF`, and `ComfyUI-LTXVideo` require workflow-specific model files under `/workspace/models`; those files stay out of the image and should be populated through the model-volume workflow.

## RunPod Runtime Environment

Optional environment variables:

```text
COMFYUI_PORT=8188
EXTRA_COMFYUI_ARGS=
ENABLE_SAGE_ATTENTION=auto
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

`ENABLE_SAGE_ATTENTION=auto` adds ComfyUI's `--use-sage-attention` flag only when the `sageattention` package imports successfully. Set it to `1` to require SageAttention and fail startup if it is missing, or `0` to force ComfyUI's default attention backend.

You can check optional accelerator availability inside a running container with:

```bash
python /opt/scripts/check-performance-deps.py
```

## Model Volume Preparation

Prepare `/workspace/models` before starting the GPU pod with the standalone model-volume tool:

```bash
cd ../comfyui-s3-model-volume-tools
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Typical workflow:

```bash
model-tools extract workflow.json --output wanted-models.csv
model-tools resolve wanted-models.csv --output resolved-models.csv
model-tools verify resolved-models.csv --target runpod-s3
model-tools ensure resolved-models.csv --target runpod-s3
```

The object key contract is:

```text
RunPod S3 key: models/unet/flux1-dev.safetensors
Pod path:      /workspace/models/unet/flux1-dev.safetensors
```

See the standalone tool README for its S3 and source-token configuration.

If the pod is already running while models are uploaded through the S3 API, ComfyUI may need a model refresh, workflow reload, or restart before newly uploaded files are visible.

Generated outputs remain under `/workspace/output`. Archive or sync them with external tooling, including `model-tools sync-generations` from the standalone model-volume project.

## Open Questions

1. What is the canonical repository URL for `ComfyUI-RunpodDirect`?
2. Which additional performance accelerators should be baked in after SageAttention has a tested baseline?
