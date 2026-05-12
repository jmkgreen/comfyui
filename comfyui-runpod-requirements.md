# ComfyUI on RunPod: Docker Image, Network Storage, and S3 Model Workflow

## Purpose

Build a new GitHub repository/image for running ComfyUI on RunPod in a cost-effective, reliable way.

The image should avoid the current fragile pattern where ComfyUI and the Python virtual environment live inside `/workspace/ComfyUI` on RunPod network storage. Instead, the Docker image should contain the application runtime, while persistent data such as models, outputs, workflows, and user configuration live on RunPod network storage.

S3 should act as the master store for model files. RunPod network storage should be treated as a local working cache for those models.

## Background / Current Pain Points

The current approach uses a minimal Docker image and keeps most of the live ComfyUI installation under `/workspace`, including ComfyUI itself and its Python virtual environment.

This causes several problems:

- Startup is slow because Python, ComfyUI, and custom node imports run from network storage.
- The environment is fragile and can become hard to diagnose after ComfyUI Manager upgrades or failed custom node installs.
- Rebuilding the network volume after startup crashes is time-consuming.
- The setup is tied to the RunPod region where the network volume exists.
- Building Docker images that include model files is too slow and can time out in GitHub Actions.
- Container volume storage is more expensive per GB than network volume storage.

## Target Architecture

### Docker Image

The Docker image should contain:

- ComfyUI source code.
- Python virtual environment or equivalent installed Python dependencies.
- PyTorch/CUDA dependencies appropriate for RunPod GPU instances.
- ComfyUI Manager.
- A baseline set of stable/custom nodes used frequently.
- Utility scripts for model syncing and generation backup.
- AWS CLI or another S3-capable sync tool.
- A startup script that wires the container to `/workspace` paths.

The image should not contain large model files.

### RunPod Network Storage

RunPod network storage should contain persistent runtime data:

```text
/workspace/models
/workspace/input
/workspace/output
/workspace/user
/workspace/workflows
/workspace/custom_nodes_experimental
/workspace/config
```

Suggested purpose of each path:

- `/workspace/models`: local working cache of models used by ComfyUI.
- `/workspace/input`: input files for ComfyUI.
- `/workspace/output`: generated images/videos.
- `/workspace/user`: ComfyUI user data and settings.
- `/workspace/workflows`: saved workflows.
- `/workspace/custom_nodes_experimental`: custom nodes installed manually or via ComfyUI Manager while experimenting.
- `/workspace/config`: repo-specific config files such as model manifest files.

### S3

S3 should be treated as the master/canonical store for model files and optional backup storage for outputs.

Suggested S3 layout:

```text
s3://<bucket>/comfyui/models/
s3://<bucket>/comfyui/generations/
s3://<bucket>/comfyui/workflows/
s3://<bucket>/comfyui/config/
```

Model files should be added to S3 first, then copied down into RunPod network storage when needed.

Generated outputs should be stored locally on RunPod network storage first. A user-triggered script should push selected generations to a dated folder in S3.

## Required Scripts

### 1. Startup Script

Provide a container startup script, for example:

```text
scripts/start.sh
```

Responsibilities:

- Ensure required `/workspace` directories exist.
- Link or configure ComfyUI so it uses persistent paths under `/workspace`.
- Link `/workspace/models` into the ComfyUI models directory.
- Link `/workspace/user` into the ComfyUI user directory if appropriate.
- Optionally link experimental custom nodes from `/workspace/custom_nodes_experimental` into the ComfyUI `custom_nodes` directory.
- Start ComfyUI with suitable RunPod options.

Expected behaviour:

- The image should work on a fresh network volume.
- The script should be idempotent.
- Re-running the script should not corrupt the environment.

### 2. Ensure Essential Models Script

Provide a script that reads a simple text manifest of required model files and ensures they exist on RunPod network storage.

Example script name:

```text
scripts/ensure-models.sh
```

Example manifest:

```text
config/essential-models.txt
```

Suggested manifest format:

```text
# Lines beginning with # are comments
# Format: <s3-relative-path> <local-relative-path>
models/checkpoints/example.safetensors checkpoints/example.safetensors
models/vae/example_vae.safetensors vae/example_vae.safetensors
models/clip/example_clip.safetensors clip/example_clip.safetensors
```

The script should:

- Read each non-comment, non-empty line.
- Check whether the destination file exists under `/workspace/models`.
- If missing, copy it from S3.
- Create parent directories as needed.
- Print clear status messages.
- Exit non-zero if any required model could not be copied.

Useful environment variables:

```text
S3_BUCKET=<bucket-name>
S3_PREFIX=comfyui
MODEL_MANIFEST=/workspace/config/essential-models.txt
MODELS_DIR=/workspace/models
```

Expected example usage:

```bash
S3_BUCKET=my-bucket scripts/ensure-models.sh
```

### 3. Sync Specific Model From S3 Script

Provide a convenience script to pull one model or prefix from S3 into `/workspace/models`.

Example script name:

```text
scripts/sync-model-from-s3.sh
```

Expected use cases:

- A new model has been manually uploaded to S3.
- The user wants to bring it down to the RunPod network volume.
- The user does not want to rebuild the Docker image.

Example usage:

```bash
scripts/sync-model-from-s3.sh models/checkpoints/new-model.safetensors checkpoints/new-model.safetensors
```

The first argument is the S3-relative path. The second argument is the local path relative to `/workspace/models`.

### 4. Push Generations To S3 Script

Provide a user-triggered script to copy generated images/videos from `/workspace/output` to a new dated folder in S3.

Example script name:

```text
scripts/push-generations-to-s3.sh
```

Expected behaviour:

- Create or target a folder based on the current date.
- Copy files from `/workspace/output` to S3.
- Use a path such as:

```text
s3://<bucket>/comfyui/generations/YYYY-MM-DD/
```

Optional improvement:

- Include a timestamp or run label to avoid mixing unrelated sessions:

```text
s3://<bucket>/comfyui/generations/YYYY-MM-DD/HHMMSS/
```

Example usage:

```bash
S3_BUCKET=my-bucket scripts/push-generations-to-s3.sh
```

Useful environment variables:

```text
S3_BUCKET=<bucket-name>
S3_PREFIX=comfyui
OUTPUT_DIR=/workspace/output
GENERATION_S3_PREFIX=comfyui/generations
```

## Docker Image Requirements

The Dockerfile should:

- Use a CUDA/PyTorch-capable base image suitable for RunPod GPU instances.
- Install system dependencies required by ComfyUI and common custom nodes.
- Clone or copy ComfyUI into a stable image path, for example `/opt/ComfyUI`.
- Install Python dependencies into an image-local virtual environment, for example `/opt/venv`.
- Install ComfyUI Manager.
- Install stable, frequently-used custom nodes during image build.
- Copy scripts into the image.
- Set the default command to the startup script.

Suggested container paths:

```text
/opt/ComfyUI
/opt/venv
/opt/scripts
```

Suggested persistent paths:

```text
/workspace/models
/workspace/input
/workspace/output
/workspace/user
/workspace/workflows
/workspace/custom_nodes_experimental
/workspace/config
```

## Custom Nodes Strategy

Use two classes of custom nodes.

### Stable Custom Nodes

Stable/frequently-used custom nodes should be installed during the Docker image build.

Advantages:

- Faster startup.
- More reproducible.
- Easier to test.
- Less likely to corrupt the network volume.

### Experimental Custom Nodes

Experimental nodes installed while trying new workflows can live under:

```text
/workspace/custom_nodes_experimental
```

The startup script can symlink them into:

```text
/opt/ComfyUI/custom_nodes
```

Once an experimental node proves useful, it should be promoted into the Docker build.

Avoid running ComfyUI Manager upgrades automatically on every startup. Instead, update ComfyUI and stable nodes periodically via GitHub, rebuild the image, and test startup.

## Reliability Requirements

Scripts should be:

- Idempotent.
- Clear in their logging.
- Safe to run repeatedly.
- Conservative about deleting files.
- Explicit when required environment variables are missing.
- Able to fail clearly when S3 credentials are not configured.

The startup flow should not mutate the image-local Python environment at runtime.

## Cost / Performance Principles

- Do not store large models inside the Docker image.
- Do not run Python or ComfyUI itself from RunPod network storage.
- Use network storage for large persistent data such as models and outputs.
- Use S3 as the master model store.
- Treat RunPod network model storage as a cache that can be repaired from S3.
- Push outputs to S3 when worth keeping long-term.
- Keep the Docker image reproducible and model-free.

## Open Decisions

Codex/build work may need to decide:

- Exact CUDA/PyTorch base image.
- Whether to use `awscli`, `rclone`, or both.
- Exact ComfyUI branch/tag pinning strategy.
- Which stable custom nodes should be installed in the image.
- Whether experimental custom nodes should be symlinked automatically or only when explicitly requested.
- Whether output uploads should use date-only folders or date-plus-time folders.
- Whether model manifest entries should support checksums.

## Nice-To-Have Enhancements

- Add SHA256 checksums to the model manifest.
- Add a dry-run mode to all S3 sync scripts.
- Add a script to generate/update the manifest from the S3 model tree.
- Add a health check that verifies ComfyUI starts and the model paths are visible.
- Add a script to back up workflows and user config to S3.
- Add GitHub Actions build and push workflow for the Docker image.
- Add a small README with common RunPod environment variables and example pod configuration.

## Initial Acceptance Criteria

A first useful version is complete when:

1. The Docker image starts ComfyUI without requiring ComfyUI or Python to exist in `/workspace`.
2. `/workspace/models` is used as the persistent model directory.
3. `/workspace/output` is used for generated files.
4. An essential model manifest can be used to restore missing models from S3.
5. A user can manually sync a new model from S3 to RunPod network storage.
6. A user can manually push generations to a dated S3 folder.
7. The image can run on a fresh RunPod network volume after creating the expected directories.

