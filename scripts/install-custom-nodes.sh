#!/usr/bin/env bash
set -Eeuo pipefail

log() {
  printf '[install-custom-nodes] %s\n' "$*"
}

die() {
  printf '[install-custom-nodes] ERROR: %s\n' "$*" >&2
  exit 1
}

CUSTOM_NODES_FILE="${1:-/opt/config/stable-custom-nodes.txt}"
COMFYUI_DIR="${COMFYUI_DIR:-/opt/ComfyUI}"
RUN_CUSTOM_NODE_INSTALL_PY="${RUN_CUSTOM_NODE_INSTALL_PY:-1}"
ONNXRUNTIME_CUDA12_INDEX="${ONNXRUNTIME_CUDA12_INDEX:-}"

[[ -f "${CUSTOM_NODES_FILE}" ]] || die "Custom nodes file not found: ${CUSTOM_NODES_FILE}"
command -v git >/dev/null 2>&1 || die "Missing required command: git"
command -v pip >/dev/null 2>&1 || die "Missing required command: pip"

mkdir -p "${COMFYUI_DIR}/custom_nodes"
touch "${COMFYUI_DIR}/custom_nodes/skip_download_model"

while IFS= read -r line || [[ -n "${line}" ]]; do
  line="${line%%#*}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  [[ -n "${line}" ]] || continue

  read -r repo_url target_dir ref extra <<<"${line}"
  [[ -n "${repo_url:-}" && -n "${target_dir:-}" ]] || die "Invalid custom node line: ${line}"
  [[ -z "${extra:-}" ]] || die "Too many fields in custom node line: ${line}"

  node_path="${COMFYUI_DIR}/custom_nodes/${target_dir}"
  if [[ -e "${node_path}" ]]; then
    log "Skipping ${target_dir}; path already exists."
    continue
  fi

  log "Cloning ${repo_url} into ${target_dir}"
  git clone --recursive "${repo_url}" "${node_path}"

  if [[ -n "${ref:-}" && "${ref}" != "-" ]]; then
    git -C "${node_path}" checkout "${ref}"
    git -C "${node_path}" submodule update --init --recursive
  fi

  if [[ -f "${node_path}/requirements.txt" ]]; then
    log "Installing requirements for ${target_dir}"
    pip_args=(install -r "${node_path}/requirements.txt")
    if [[ "${target_dir}" == "comfyui_controlnet_aux" && -n "${ONNXRUNTIME_CUDA12_INDEX}" ]]; then
      pip_args+=(--extra-index-url "${ONNXRUNTIME_CUDA12_INDEX}")
    fi
    pip "${pip_args[@]}"
  fi

  if [[ "${RUN_CUSTOM_NODE_INSTALL_PY}" == "1" && -f "${node_path}/install.py" ]]; then
    log "Running install.py for ${target_dir}"
    (cd "${node_path}" && python install.py)
  fi
done < "${CUSTOM_NODES_FILE}"

log "Stable custom node installation complete."
