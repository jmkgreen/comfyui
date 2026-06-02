# Portable VM Use Plan

## Goal

Create a build and launch variation that can run the same ComfyUI image on RunPod or a generic GPU VM provider. RunPod should remain the lowest-friction default, but the image should not require RunPod-specific storage, networking, or model-preparation assumptions.

The target operating model is:

1. Provision any GPU host that can run NVIDIA Docker.
2. Connect to it by a provider-appropriate control channel, such as SSH or AWS SSM.
3. Start the ComfyUI container with an explicit persistent data mount.
4. Run a remote bootstrap step that prepares the model directory before or during first launch.
5. Keep all large model files out of the image.

## Current Findings

The current image already has a useful separation between image-local application code and persistent runtime data.

Image-local paths:

```text
/opt/ComfyUI
/opt/venv
/opt/scripts
```

Runtime data defaults:

```text
WORKSPACE_DIR=/workspace
MODELS_DIR=/workspace/models
INPUT_DIR=/workspace/input
OUTPUT_DIR=/workspace/output
USER_DIR=/workspace/user
WORKFLOWS_DIR=/workspace/workflows
CONFIG_DIR=/workspace/config
EXPERIMENTAL_CUSTOM_NODES_DIR=/workspace/custom_nodes_experimental
```

`scripts/start.sh` already allows these paths to be overridden with environment variables. It creates the expected data directories, replaces the image-local `models`, `input`, `output`, and `user` directories with symlinks, and launches ComfyUI with explicit `--input-directory`, `--output-directory`, and `--user-directory` arguments.

The main RunPod assumption is therefore mostly documentation and defaults, not a hard dependency. The Dockerfile sets `WORKSPACE_DIR=/workspace` and creates `/workspace`, and the README describes RunPod network storage as the primary runtime contract.

Other current provider-sensitive areas:

- SSH is built into the image and starts by default when `SSH_ENABLE=1`.
- Jupyter starts by default and is rooted at `JUPYTER_ROOT_DIR`, which defaults to `WORKSPACE_DIR`.
- `s5cmd`, `awscli`, and `huggingface_hub` are installed in the image, which gives us enough primitives for S3-compatible storage, AWS S3, and Hugging Face downloads.
- The existing model workflow is built around the adjacent `../comfyui-s3-model-volume-tools` project and RunPod's S3-compatible network volume API.
- `scripts/prepare-workflow.py` is provider-neutral as long as it receives the right manifest and `--models-root`.

## Proposed Build Variation

Add a provider-neutral image tag or build target, tentatively named `comfyui-vm`, that uses the same Dockerfile and runtime scripts unless we discover a real need for a separate Dockerfile.

Recommended first step:

```bash
docker build -t comfyui-vm .
```

Then document provider-specific launch recipes rather than fork the image. The current Dockerfile is already suitable for this because `/workspace` can simply be a conventional in-container mount point on non-RunPod hosts.

Only split the Dockerfile if we need a real image difference, for example:

- disabling SSH/Jupyter defaults for hardened cloud deployments;
- installing provider-specific agents inside the container, which is probably undesirable;
- using a different CUDA/PyTorch base image for a VM fleet.

## Runtime Directory Contract

The portable contract should be:

```text
Container app root:     /opt/ComfyUI
Container scripts root: /opt/scripts
Container data root:    configurable, default /workspace
Host data root:         configurable per provider
```

For maximum compatibility, keep `/workspace` as the default container path everywhere. On providers that do not have RunPod network volumes, mount any durable host path there:

```bash
docker run --gpus all \
  -p 8188:8188 \
  -p 8888:8888 \
  -v /mnt/comfyui-workspace:/workspace \
  -e JUPYTER_TOKEN="$JUPYTER_TOKEN" \
  comfyui-vm
```

If a provider has a strong reason to use a different path inside the container, set `WORKSPACE_DIR` and optionally the more specific path variables:

```bash
docker run --gpus all \
  -p 8188:8188 \
  -v /mnt/comfyui:/data \
  -e WORKSPACE_DIR=/data \
  comfyui-vm
```

The startup script should continue to derive `MODELS_DIR`, `INPUT_DIR`, `OUTPUT_DIR`, `USER_DIR`, `WORKFLOWS_DIR`, `CONFIG_DIR`, and `EXPERIMENTAL_CUSTOM_NODES_DIR` from `WORKSPACE_DIR` unless explicitly overridden.

## Environment Discovery

Add a lightweight discovery layer to `scripts/start.sh`, or a small script called by it, with this order of precedence:

1. Explicit environment variables always win.
2. If `/workspace` exists or can be created, use it.
3. If common VM mount points exist, choose the first writable candidate and log the choice.
4. If no durable mount is detected, fall back to `/workspace` and warn clearly that data may be ephemeral unless the path is bind-mounted.

Candidate host/container data roots to recognize:

```text
/workspace
/data
/mnt/comfyui
/mnt/workspace
/mnt/data
```

This should be detection, not magic. The log should say exactly which directory is being used and how to override it:

```text
[start] Runtime provider: generic-vm
[start] Workspace: /workspace
[start] Models: /workspace/models
```

Provider hints can be optional:

```text
COMFYUI_PROVIDER=runpod
COMFYUI_PROVIDER=aws-ec2
COMFYUI_PROVIDER=generic-vm
```

The script can infer `runpod` when known RunPod environment variables are present, but the implementation should not require those variables.

## Remote Bootstrap Shape

Add a host-side bootstrap script in a later implementation pass, for example:

```text
scripts/vm-bootstrap.sh
scripts/vm-run-remote.sh
```

The bootstrap should run outside the ComfyUI container where possible, because the host is where provider credentials, durable disks, and Docker lifecycle controls live.

Responsibilities:

1. Verify NVIDIA Docker works:

   ```bash
   docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi
   ```

2. Create the host workspace directory.
3. Pull or build the image.
4. Start the container with the workspace mounted.
5. Run model preparation into the mounted `models` directory.
6. Optionally restart ComfyUI after models are downloaded.

The remote runner should support at least two transports:

```text
ssh
aws-ssm
```

Suggested command shape:

```bash
scripts/vm-run-remote.sh \
  --transport ssh \
  --host ubuntu@gpu.example.com \
  --workspace /mnt/comfyui-workspace \
  --image comfyui-vm:latest \
  --manifest resolved-models.csv
```

For AWS SSM:

```bash
scripts/vm-run-remote.sh \
  --transport aws-ssm \
  --instance-id i-xxxxxxxxxxxxxxxxx \
  --region eu-west-2 \
  --workspace /mnt/comfyui-workspace \
  --image comfyui-vm:latest \
  --manifest resolved-models.csv
```

## Model Download Options

There are three viable model-population modes.

### Mode A: Existing S3-Compatible Flow

Keep using `comfyui-s3-model-volume-tools` to populate object storage before the GPU host starts. On RunPod this targets the RunPod network volume S3 API. On AWS this could target S3 directly, then the VM bootstrap syncs down to the mounted workspace.

Best for:

- repeatable model inventories;
- avoiding long downloads on expensive GPU runtime;
- hosts with weak outbound bandwidth but good object-store access.

### Mode B: Remote Download Into Mounted Workspace

Run model download commands on the VM over SSH or SSM, writing directly to:

```text
${HOST_WORKSPACE}/models
```

When mounted into the container, this becomes:

```text
/workspace/models
```

Best for:

- generic cloud VMs;
- providers without RunPod-style network volumes;
- one-off spot instances.

### Mode C: In-Container Download Job

Start the container with ComfyUI disabled or paused, exec a model download command inside it, then start ComfyUI. This is convenient because the image already has `awscli`, `s5cmd`, and Hugging Face tooling.

This needs a small startup option such as:

```text
COMFYUI_START_MODE=serve
COMFYUI_START_MODE=prepare
COMFYUI_START_MODE=shell
```

This mode is useful, but should not be the only path because provider credentials are usually cleaner on the host.

## Proposed Implementation Phases

### Phase 1: Document and Normalize

- Keep `/workspace` as the container default.
- Update docs to describe `/workspace` as the portable data root, not only the RunPod data root.
- Add examples for RunPod, generic SSH VM, and AWS EC2.
- Avoid changing image behavior yet.

### Phase 2: Startup Discovery

- Add provider/workspace discovery to `scripts/start.sh`.
- Make discovery purely additive; explicit env vars keep current behavior.
- Log detected provider, workspace, and persistence warnings.
- Add a `COMFYUI_REQUIRE_PERSISTENT_WORKSPACE=1` option that fails startup if the chosen workspace looks ephemeral.

### Phase 3: Remote Bootstrap

- Add `scripts/vm-run-remote.sh` as the orchestration wrapper.
- Add a provider-neutral remote payload script, for example `scripts/vm-bootstrap-host.sh`.
- Implement SSH transport first.
- Implement AWS SSM after SSH behavior is stable.
- Keep model download source configuration outside the image, using manifests and environment variables.

### Phase 4: Optional Image Entrypoint Modes

- Add `COMFYUI_START_MODE=serve|prepare|shell`.
- In `prepare` mode, create directories and optionally run a configured model command without starting ComfyUI.
- Keep the default as `serve` for compatibility.

## Security Notes

- Keep SSH disabled or key-only when the provider already supplies a secure control plane.
- Prefer host-level SSH or AWS SSM for VM orchestration rather than exposing container SSH publicly.
- If container SSH remains enabled, require `SSH_PUBLIC_KEY`, `PUBLIC_KEY`, or a mounted authorized keys file.
- Do not bake cloud credentials or Hugging Face tokens into the image.
- Treat Jupyter as a privileged remote shell. Keep `JUPYTER_TOKEN` set when port `8888` is exposed.

## Questions To Answer

1. Should the portable VM path use the same Docker image tag with different launch docs, or do you want a distinct published tag such as `comfyui-vm`?
2. Should model download happen primarily on the host, inside the running container, or both?
3. For AWS, do you want SSM as a first-class transport in the first implementation, or should SSH land first?
4. Where should the canonical model manifest live for remote bootstrap: this repo, the adjacent `comfyui-s3-model-volume-tools` repo, or an external artifact location?
5. Should non-RunPod VMs preserve generated outputs on the same mounted workspace, or sync them back to object storage automatically?
6. Should container SSH default to off for generic VM deployments, relying on host SSH/SSM instead?
7. Which VM providers should the examples prioritize after AWS EC2?

## Recommended Next Move

Implement Phase 1 and Phase 2 together. That keeps the first code change small: make startup discovery clearer, preserve `/workspace` compatibility, and add enough logging that RunPod and generic VMs are easy to reason about from container logs.

After that, build the SSH remote bootstrap as the first real provider-neutral launcher. AWS SSM can reuse the same remote payload once the host bootstrap is stable.
