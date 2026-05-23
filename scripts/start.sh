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
ENABLE_SAGE_ATTENTION="${ENABLE_SAGE_ATTENTION:-auto}"
JUPYTER_ENABLE="${JUPYTER_ENABLE:-1}"
JUPYTER_HOST="${JUPYTER_HOST:-0.0.0.0}"
JUPYTER_PORT="${JUPYTER_PORT:-8888}"
JUPYTER_ROOT_DIR="${JUPYTER_ROOT_DIR:-${WORKSPACE_DIR}}"
JUPYTER_TOKEN="${JUPYTER_TOKEN:-}"
JUPYTER_ALLOW_ORIGIN="${JUPYTER_ALLOW_ORIGIN:-*}"
JUPYTER_TRUST_XHEADERS="${JUPYTER_TRUST_XHEADERS:-1}"
SSH_ENABLE="${SSH_ENABLE:-1}"
SSH_PORT="${SSH_PORT:-22}"
SSH_PUBLIC_KEY="${SSH_PUBLIC_KEY:-}"
PUBLIC_KEY="${PUBLIC_KEY:-}"
SSH_AUTHORIZED_KEYS_FILE="${SSH_AUTHORIZED_KEYS_FILE:-${CONFIG_DIR}/authorized_keys}"

mkdir -p \
  "${MODELS_DIR}" \
  "${INPUT_DIR}" \
  "${OUTPUT_DIR}" \
  "${USER_DIR}" \
  "${USER_DIR}/default" \
  "${WORKFLOWS_DIR}" \
  "${CONFIG_DIR}" \
  "${EXPERIMENTAL_CUSTOM_NODES_DIR}"

if [[ -L "${COMFYUI_DIR}/models" || -e "${COMFYUI_DIR}/models" ]]; then
  rm -rf "${COMFYUI_DIR}/models"
fi
ln -s "${MODELS_DIR}" "${COMFYUI_DIR}/models"

if [[ -L "${COMFYUI_DIR}/input" || -e "${COMFYUI_DIR}/input" ]]; then
  rm -rf "${COMFYUI_DIR}/input"
fi
ln -s "${INPUT_DIR}" "${COMFYUI_DIR}/input"

if [[ -L "${COMFYUI_DIR}/output" || -e "${COMFYUI_DIR}/output" ]]; then
  rm -rf "${COMFYUI_DIR}/output"
fi
ln -s "${OUTPUT_DIR}" "${COMFYUI_DIR}/output"

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
log "Input: ${INPUT_DIR}"
log "Output: ${OUTPUT_DIR}"
log "User data: ${USER_DIR}"
log "Listening on ${COMFYUI_HOST}:${COMFYUI_PORT}"

if [[ "${SSH_ENABLE}" == "1" ]]; then
  mkdir -p /run/sshd /root/.ssh
  chmod 700 /root/.ssh

  if [[ -n "${SSH_PUBLIC_KEY}" ]]; then
    printf '%s\n' "${SSH_PUBLIC_KEY}" > /root/.ssh/authorized_keys
  elif [[ -n "${PUBLIC_KEY}" ]]; then
    printf '%s\n' "${PUBLIC_KEY}" > /root/.ssh/authorized_keys
  elif [[ -f "${SSH_AUTHORIZED_KEYS_FILE}" ]]; then
    cp "${SSH_AUTHORIZED_KEYS_FILE}" /root/.ssh/authorized_keys
  fi

  if [[ -f /root/.ssh/authorized_keys ]]; then
    chmod 600 /root/.ssh/authorized_keys
  else
    log "SSH enabled, but no authorized keys found. Set SSH_PUBLIC_KEY, PUBLIC_KEY, or mount ${SSH_AUTHORIZED_KEYS_FILE}."
  fi

  ssh-keygen -A
  log "Starting sshd on 0.0.0.0:${SSH_PORT}"
  /usr/sbin/sshd \
    -o "Port=${SSH_PORT}" \
    -o "PermitRootLogin=prohibit-password" \
    -o "PasswordAuthentication=no" \
    -o "KbdInteractiveAuthentication=no" \
    -o "ChallengeResponseAuthentication=no" \
    -o "PubkeyAuthentication=yes" \
    -o "PermitEmptyPasswords=no" \
    -o "AllowUsers=root" \
    -o "AllowAgentForwarding=no" \
    -o "X11Forwarding=no" \
    -o "PermitTunnel=no" \
    -o "GatewayPorts=no" \
    -o "LoginGraceTime=30" \
    -o "MaxAuthTries=3" \
    -o "MaxSessions=4" \
    -o "KexAlgorithms=curve25519-sha256,curve25519-sha256@libssh.org" \
    -o "HostKeyAlgorithms=ssh-ed25519" \
    -o "PubkeyAcceptedAlgorithms=ssh-ed25519" \
    -o "Ciphers=chacha20-poly1305@openssh.com,aes256-gcm@openssh.com,aes128-gcm@openssh.com,aes256-ctr,aes128-ctr" \
    -o "MACs=hmac-sha2-512-etm@openssh.com,hmac-sha2-256-etm@openssh.com,umac-128-etm@openssh.com"
else
  log "SSH disabled with SSH_ENABLE=${SSH_ENABLE}"
fi

sage_attention_args=()
case "${ENABLE_SAGE_ATTENTION}" in
  1|auto)
    sage_attention_check_args=(--smoke)
    if python "${SCRIPTS_DIR:-/opt/scripts}/check-sage-attention.py" "${sage_attention_check_args[@]}"; then
      sage_attention_args+=(--use-sage-attention)
      log "SageAttention enabled."
    elif [[ "${ENABLE_SAGE_ATTENTION}" == "1" ]]; then
      log "ERROR: ENABLE_SAGE_ATTENTION=1 but SageAttention failed validation."
      exit 1
    else
      log "SageAttention failed validation; continuing with ComfyUI's default attention backend."
    fi
    ;;
  0|false|False|FALSE)
    log "SageAttention disabled with ENABLE_SAGE_ATTENTION=${ENABLE_SAGE_ATTENTION}."
    ;;
  *)
    log "ERROR: ENABLE_SAGE_ATTENTION must be auto, 1, or 0."
    exit 1
    ;;
esac

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
  "${sage_attention_args[@]}" \
  ${EXTRA_COMFYUI_ARGS} \
  "$@"
