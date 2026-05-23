# ComfyUI on RunPod: Runtime Image Requirements

## Purpose

Build a reliable Docker image for running ComfyUI on RunPod.

This repository owns the GPU runtime:

- ComfyUI source and Python dependencies,
- selected stable custom nodes,
- optional performance accelerators,
- startup wiring for RunPod network storage,
- Jupyter access for inspection and light file management.

Model discovery, source resolution, and network-volume population are out of scope for this repository. Those concerns live in the adjacent standalone project:

```text
../comfyui-s3-model-volume-tools
```

## Runtime Architecture

The Docker image should contain the application runtime. Persistent user data should live on the RunPod network volume mounted at `/workspace`.

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

The startup script should:

- create the expected `/workspace` directories,
- symlink `/opt/ComfyUI/models`, `/opt/ComfyUI/input`, `/opt/ComfyUI/output`, and `/opt/ComfyUI/user` to the matching `/workspace` directories,
- optionally symlink experimental custom nodes from `/workspace/custom_nodes_experimental`,
- start ComfyUI with `/workspace/input`, `/workspace/output`, and `/workspace/user`,
- optionally start Jupyter Lab rooted at `/workspace`.

The image should not contain large model files.

## Docker Image Requirements

The Dockerfile should:

- use a CUDA/PyTorch devel-capable base image when CUDA extensions are installed at build time,
- install system dependencies required by ComfyUI and common custom nodes,
- install compiler/build dependencies required by CUDA-backed accelerators,
- install custom-node build dependencies required by the stable plugin set, including CMake for ComfyUI-3D-Pack,
- clone ComfyUI into `/opt/ComfyUI`,
- install Python dependencies into `/opt/venv`,
- install ComfyUI Manager,
- install stable custom nodes during image build,
- install SageAttention during image build by default, pinned to a known-good version,
- install CUDA 12 ONNX Runtime support for `comfyui_controlnet_aux` from the CUDA 12 package index when building CUDA 12 images,
- copy runtime scripts into `/opt/scripts`,
- set the default command to `scripts/start.sh`.

## Custom Nodes Strategy

Stable/frequently-used custom nodes should be installed during image build for faster startup and better reproducibility.

Initial stable node set:

- `ComfyUI_essentials`
- `ComfyUI-Easy-Use`
- `ComfyUI-Impact-Pack`
- `ComfyUI-Impact-Subpack`
- `ComfyUI-KJNodes`
- `ComfyUI-WanVideoWrapper`
- `rgthree-comfy`
- `cg-use-everywhere`
- `seedvr2_videoupscaler`
- `ComfyUI-Crystools`
- `ComfyUI_IPAdapter_plus`
- `comfyui_controlnet_aux`
- `ComfyUI-GGUF`
- `ComfyUI-LTXVideo`

Stable node install notes:

- `ComfyUI-Crystools`: install `requirements.txt`; GPU monitoring depends on NVIDIA/CUDA runtime visibility.
- `ComfyUI_IPAdapter_plus`: no extra build step beyond clone, but IPAdapter and CLIP Vision models must be present under `/workspace/models`.
- `comfyui_controlnet_aux`: install `requirements.txt`; CUDA 12 images should install `onnxruntime-gpu` through the CUDA 12 package index.
- `ComfyUI-3D-Pack`: disabled from the default baked stable image until PyTorch3D and related native wheels match the Python 3.12 + Torch 2.10 + CUDA 12.8 image stack reliably. Test it only through an alternate custom-node list or experimental node mount.
- `ComfyUI-GGUF`: install `requirements.txt`, primarily `gguf`, and place `.gguf` diffusion/text-encoder models under `/workspace/models`.
- `ComfyUI-LTXVideo`: install `requirements.txt`; LTX model checkpoints, latent upscalers, LoRAs, and Gemma text encoder files remain model-volume contents.

Experimental custom nodes can live under:

```text
/workspace/custom_nodes_experimental
```

The startup script may symlink those directories into:

```text
/opt/ComfyUI/custom_nodes
```

Once an experimental node proves useful, promote it into the Docker build.

## Performance Accelerator Requirements

The image should make high-impact inference optimisations available without making startup fragile.

### SageAttention

SageAttention is the first baked-in accelerator.

Requirements:

- Install `sageattention` during Docker build, not pod startup.
- Pin the SageAttention version, starting with `2.2.0` for the current image line unless testing proves a different version is needed.
- Use a CUDA devel base image with compiler tooling.
- Verify the package imports during image build.
- Add ComfyUI's `--use-sage-attention` flag automatically only when the package imports successfully.
- Add ComfyUI's `--enable-assets` flag by default so existing `/workspace/input` and `/workspace/output` files are indexed for the Assets menu on new pod launches.
- Provide `ENABLE_SAGE_ATTENTION=auto|1|0`.
- Provide `ENABLE_COMFYUI_ASSETS=1|0`.

`ENABLE_SAGE_ATTENTION` behavior:

- `auto`: enable the flag when import succeeds and otherwise fall back.
- `1`: require SageAttention and fail clearly if unavailable.
- `0`: disable SageAttention even when installed.

### Further Accelerator Candidates

Consider these after SageAttention has a tested baseline:

- `xformers`,
- `flash-attn`,
- newer PyTorch SDPA behavior,
- quantization/runtime helpers used by the selected custom-node set,
- startup diagnostics for accelerator imports and backend choices.

## Reliability Requirements

The startup flow should:

- be idempotent,
- avoid mutating the image-local Python environment at runtime,
- log clearly,
- fail clearly for invalid accelerator configuration,
- work on a fresh RunPod network volume after creating expected directories,
- avoid deleting user data outside managed symlink targets.

## Model Volume Boundary

The ComfyUI pod consumes `/workspace/models`; it does not prepare the model volume.

Use `../comfyui-s3-model-volume-tools` to:

- extract model names from workflows,
- resolve reviewed CSV manifests,
- verify RunPod network-volume contents through S3,
- download and upload missing models before starting the GPU pod,
- archive generations when desired.

This separation keeps GPU pods disposable and avoids spending GPU time on model discovery or repair.

## Initial Acceptance Criteria

A first useful runtime image is complete when:

1. The Docker image starts ComfyUI without requiring ComfyUI or Python to exist in `/workspace`.
2. `/workspace/models` is used as the persistent model directory.
3. `/workspace/output` is used for generated files.
4. `/workspace/user` is used for persistent ComfyUI user data.
5. Jupyter can optionally start rooted at `/workspace`.
6. SageAttention is available and auto-enabled when installed.
7. Startup still succeeds with default attention when `ENABLE_SAGE_ATTENTION=auto` and SageAttention is unavailable.
8. Stable custom nodes are baked into the image.
9. Experimental custom nodes can be mounted through `/workspace/custom_nodes_experimental`.

## Open Decisions

- Exact CUDA/PyTorch base image.
- Exact GPU family target for the default build.
- Exact ComfyUI branch/tag pinning strategy.
- Exact SageAttention/PyTorch/CUDA compatibility matrix.
- Whether to bake xFormers and FlashAttention into the image or keep them build-arg controlled.
- Which stable custom nodes should be installed in the image.
- Whether experimental custom nodes should be symlinked automatically or only when explicitly requested.
