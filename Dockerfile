ARG BASE_IMAGE=pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel
FROM ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive
ARG COMFYUI_REPO=https://github.com/comfyanonymous/ComfyUI.git
ARG COMFYUI_REF=master
ARG COMFYUI_MANAGER_REPO=https://github.com/ltdrdata/ComfyUI-Manager.git
ARG COMFYUI_MANAGER_REF=main
ARG CUSTOM_NODES_FILE=/opt/config/stable-custom-nodes.txt
ARG RUN_CUSTOM_NODE_INSTALL_PY=1
ARG INSTALL_SAGEATTENTION=1
ARG SAGEATTENTION_VERSION=2.2.0
ARG SAGEATTENTION_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0"
ARG ONNXRUNTIME_CUDA12_INDEX=https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/

ENV COMFYUI_DIR=/opt/ComfyUI \
    VENV_DIR=/opt/venv \
    SCRIPTS_DIR=/opt/scripts \
    WORKSPACE_DIR=/workspace \
    CUDA_HOME=/usr/local/cuda \
    ONNXRUNTIME_CUDA12_INDEX=${ONNXRUNTIME_CUDA12_INDEX} \
    TINI_SUBREAPER=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:/usr/local/cuda/bin:${PATH}"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update && apt-get install -y --no-install-recommends \
      awscli \
      build-essential \
      ca-certificates \
      cmake \
      curl \
      ffmpeg \
      git \
      libgl1 \
      libglib2.0-0 \
      libgomp1 \
      libsm6 \
      libxext6 \
      libxrender1 \
      ninja-build \
      openssh-client \
      python3-venv \
      rsync \
      tini \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv --system-site-packages "${VENV_DIR}" \
    && "${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel \
    && "${VENV_DIR}/bin/pip" install jupyterlab ipywidgets

RUN git clone "${COMFYUI_REPO}" "${COMFYUI_DIR}" \
    && cd "${COMFYUI_DIR}" \
    && git checkout "${COMFYUI_REF}" \
    && pip install -r requirements.txt

RUN if [[ "${INSTALL_SAGEATTENTION}" == "1" ]]; then \
      TORCH_CUDA_ARCH_LIST="${SAGEATTENTION_CUDA_ARCH_LIST}" \
      pip install "git+https://github.com/thu-ml/SageAttention.git@v${SAGEATTENTION_VERSION}" --no-build-isolation \
      && python -c "import sageattention; print('SageAttention import OK')"; \
    else \
      echo "Skipping SageAttention install because INSTALL_SAGEATTENTION=${INSTALL_SAGEATTENTION}"; \
    fi

RUN mkdir -p "${COMFYUI_DIR}/custom_nodes" \
    && git clone "${COMFYUI_MANAGER_REPO}" "${COMFYUI_DIR}/custom_nodes/ComfyUI-Manager" \
    && cd "${COMFYUI_DIR}/custom_nodes/ComfyUI-Manager" \
    && git checkout "${COMFYUI_MANAGER_REF}" \
    && if [[ -f requirements.txt ]]; then pip install -r requirements.txt; fi

COPY scripts/ "${SCRIPTS_DIR}/"
COPY config/ /opt/config/

RUN find "${SCRIPTS_DIR}" -maxdepth 1 -type f \( -name '*.sh' -o -name '*.py' \) -exec chmod +x {} + \
    && "${SCRIPTS_DIR}/install-custom-nodes.sh" "${CUSTOM_NODES_FILE}" \
    && mkdir -p /workspace

WORKDIR ${COMFYUI_DIR}
EXPOSE 8188 8888

ENTRYPOINT ["/usr/bin/tini", "-s", "--"]
CMD ["/opt/scripts/start.sh"]
