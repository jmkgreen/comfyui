#!/usr/bin/env bash
set -Eeuo pipefail

log() {
  printf '[start] %s\n' "$*"
}

COMFYUI_DIR="${COMFYUI_DIR:-/opt/ComfyUI}"
WORKSPACE_DIR="${WORKSPACE_DIR:-/workspace}"
MODELS_DIR="${MODELS_DIR:-${WORKSPACE_DIR}/models}"
INPUT_DIR="${INPUT_DIR:-${WORKSPACE_DIR}/input}"
OUTPUT_DIR="${OUTPUT_DIR:-${WORKSPACE_DIR}/output}"
USER_DIR="${USER_DIR:-${WORKSPACE_DIR}/user}"
WORKFLOWS_DIR="${WORKFLOWS_DIR:-${WORKSPACE_DIR}/workflows}"
CONFIG_DIR="${CONFIG_DIR:-${WORKSPACE_DIR}/config}"
EXPERIMENTAL_CUSTOM_NODES_DIR="${EXPERIMENTAL_CUSTOM_NODES_DIR:-${WORKSPACE_DIR}/custom_nodes_experimental}"
ENABLE_EXPERIMENTAL_CUSTOM_NODES="${ENABLE_EXPERIMENTAL_CUSTOM_NODES:-1}"
COMFYUI_HOST="${COMFYUI_HOST:-0.0.0.0}"
COMFYUI_PORT="${COMFYUI_PORT:-8188}"
EXTRA_COMFYUI_ARGS="${EXTRA_COMFYUI_ARGS:-}"
JUPYTER_ENABLE="${JUPYTER_ENABLE:-1}"
JUPYTER_HOST="${JUPYTER_HOST:-0.0.0.0}"
JUPYTER_PORT="${JUPYTER_PORT:-8888}"
JUPYTER_ROOT_DIR="${JUPYTER_ROOT_DIR:-${WORKSPACE_DIR}}"
JUPYTER_TOKEN="${JUPYTER_TOKEN:-}"
JUPYTER_ALLOW_ORIGIN="${JUPYTER_ALLOW_ORIGIN:-*}"
JUPYTER_TRUST_XHEADERS="${JUPYTER_TRUST_XHEADERS:-1}"

mkdir -p \
  "${MODELS_DIR}" \
  "${INPUT_DIR}" \
  "${OUTPUT_DIR}" \
  "${USER_DIR}" \
  "${USER_DIR}/default" \
  "${WORKFLOWS_DIR}" \
  "${CONFIG_DIR}" \
  "${EXPERIMENTAL_CUSTOM_NODES_DIR}"

if [[ ! -e "${CONFIG_DIR}/essential-models.txt" && -f /opt/config/essential-models.txt ]]; then
  cp /opt/config/essential-models.txt "${CONFIG_DIR}/essential-models.txt"
fi

if [[ -L "${COMFYUI_DIR}/models" || -e "${COMFYUI_DIR}/models" ]]; then
  rm -rf "${COMFYUI_DIR}/models"
fi
ln -s "${MODELS_DIR}" "${COMFYUI_DIR}/models"

if [[ -L "${COMFYUI_DIR}/user" || -e "${COMFYUI_DIR}/user" ]]; then
  rm -rf "${COMFYUI_DIR}/user"
fi
ln -s "${USER_DIR}" "${COMFYUI_DIR}/user"

if [[ "${ENABLE_EXPERIMENTAL_CUSTOM_NODES}" == "1" ]]; then
  mkdir -p "${COMFYUI_DIR}/custom_nodes"
  while IFS= read -r -d '' node_path; do
    node_name="$(basename "${node_path}")"
    target="${COMFYUI_DIR}/custom_nodes/${node_name}"
    if [[ -e "${target}" && ! -L "${target}" ]]; then
      log "Skipping experimental node ${node_name}; image already has a custom node at that path."
      continue
    fi
    ln -sfn "${node_path}" "${target}"
  done < <(find "${EXPERIMENTAL_CUSTOM_NODES_DIR}" -mindepth 1 -maxdepth 1 -type d -print0)
fi

log "ComfyUI: ${COMFYUI_DIR}"
log "Models: ${MODELS_DIR}"
log "Output: ${OUTPUT_DIR}"
log "User data: ${USER_DIR}"
log "Listening on ${COMFYUI_HOST}:${COMFYUI_PORT}"

if [[ "${JUPYTER_ENABLE}" == "1" ]]; then
  jupyter_args=(
    lab
    --no-browser
    --allow-root
    --ip="${JUPYTER_HOST}"
    --port="${JUPYTER_PORT}"
    --ServerApp.root_dir="${JUPYTER_ROOT_DIR}"
    --ServerApp.allow_origin="${JUPYTER_ALLOW_ORIGIN}"
    --ServerApp.trust_xheaders="${JUPYTER_TRUST_XHEADERS}"
  )

  if [[ -n "${JUPYTER_TOKEN}" ]]; then
    jupyter_args+=(--ServerApp.token="${JUPYTER_TOKEN}")
  fi

  log "Starting Jupyter Lab on ${JUPYTER_HOST}:${JUPYTER_PORT} with root ${JUPYTER_ROOT_DIR}"
  jupyter "${jupyter_args[@]}" &
else
  log "Jupyter Lab disabled with JUPYTER_ENABLE=${JUPYTER_ENABLE}"
fi

# shellcheck disable=SC2086
exec python "${COMFYUI_DIR}/main.py" \
  --listen "${COMFYUI_HOST}" \
  --port "${COMFYUI_PORT}" \
  --input-directory "${INPUT_DIR}" \
  --output-directory "${OUTPUT_DIR}" \
  --user-directory "${USER_DIR}" \
  ${EXTRA_COMFYUI_ARGS} \
  "$@"
