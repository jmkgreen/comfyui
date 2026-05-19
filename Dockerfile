ARG BASE_IMAGE=pytorch/pytorch:2.10.0-cuda12.8-cudnn9-devel
FROM ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive
ARG COMFYUI_REPO=https://github.com/comfyanonymous/ComfyUI.git
ARG COMFYUI_REF=master
ARG COMFYUI_MANAGER_REPO=https://github.com/ltdrdata/ComfyUI-Manager.git
ARG COMFYUI_MANAGER_REF=main
ARG CUSTOM_NODES_FILE=/opt/config/stable-custom-nodes.txt
ARG RUN_CUSTOM_NODE_INSTALL_PY=1
ARG INSTALL_SAGEATTENTION=1
ARG SAGEATTENTION_WHEEL_URL=https://github.com/Comfy-Org/wheels/releases/download/sageattention-latest/sageattention-2.2.0%2Bcu128torch2.10-cp312-cp312-manylinux_2_34_x86_64.manylinux_2_35_x86_64.whl
ARG ONNXRUNTIME_CUDA12_INDEX=https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/

ENV COMFYUI_DIR=/opt/ComfyUI \
    VENV_DIR=/opt/venv \
    PIP_CONSTRAINT=/opt/python-constraints.txt \
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
      build-essential \
      ca-certificates \
      cmake \
      curl \
      ffmpeg \
      git \
      libgl1 \
      libglib2.0-0 \
      libgomp1 \
      libopengl0 \
      libsm6 \
      libxext6 \
      libxrender1 \
      ninja-build \
      openssh-client \
      python3-venv \
      rsync \
      tini \
    && rm -rf /var/lib/apt/lists/*

RUN printf '%s\n' \
      'requests>=2.32.5,<3' \
      'urllib3>=1.26.18,<3' \
      'charset-normalizer>=2,<4' \
      'chardet>=3,<6' \
      'torch>=2.10,<2.11' \
      'torchvision>=0.25,<0.26' \
      'torchaudio>=2.10,<2.11' \
      > "${PIP_CONSTRAINT}"

RUN python -m venv --system-site-packages "${VENV_DIR}" \
    && "${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel \
    && "${VENV_DIR}/bin/pip" install requests urllib3 charset-normalizer chardet \
    && "${VENV_DIR}/bin/pip" install awscli jupyterlab ipywidgets

RUN git clone "${COMFYUI_REPO}" "${COMFYUI_DIR}" \
    && cd "${COMFYUI_DIR}" \
    && git checkout "${COMFYUI_REF}" \
    && pip install -r requirements.txt

RUN mkdir -p "${COMFYUI_DIR}/custom_nodes" \
    && git clone "${COMFYUI_MANAGER_REPO}" "${COMFYUI_DIR}/custom_nodes/ComfyUI-Manager" \
    && cd "${COMFYUI_DIR}/custom_nodes/ComfyUI-Manager" \
    && git checkout "${COMFYUI_MANAGER_REF}" \
    && if [[ -f requirements.txt ]]; then pip install -r requirements.txt; fi

COPY scripts/ "${SCRIPTS_DIR}/"
COPY config/ /opt/config/

RUN find "${SCRIPTS_DIR}" -maxdepth 1 -type f \( -name '*.sh' -o -name '*.py' \) -exec chmod +x {} + \
    && "${SCRIPTS_DIR}/install-custom-nodes.sh" "${CUSTOM_NODES_FILE}" \
    && python "${SCRIPTS_DIR}/repair-3d-pack-deps.py" \
    && python "${SCRIPTS_DIR}/patch-numpy2-compat.py" \
    && mkdir -p /workspace

RUN python -c "import warnings; warnings.filterwarnings('error', message='.*urllib3.*supported version.*'); import requests, urllib3; print(f'Requests: {requests.__version__}; urllib3: {urllib3.__version__}')"

RUN python -c "import torch; assert torch.__version__.startswith('2.10.'), f'SageAttention wheel requires torch 2.10.x, got {torch.__version__}'; print(f'Torch: {torch.__version__}; CUDA: {torch.version.cuda}')"

RUN if [[ "${INSTALL_SAGEATTENTION}" == "1" ]]; then \
      pip install --force-reinstall --no-deps "${SAGEATTENTION_WHEEL_URL}" \
      && python -c "import torch, sageattention; print(f'Torch: {torch.__version__}'); print('SageAttention import OK')"; \
    else \
      echo "Skipping SageAttention install because INSTALL_SAGEATTENTION=${INSTALL_SAGEATTENTION}"; \
    fi

WORKDIR ${COMFYUI_DIR}
EXPOSE 8188 8888

ENTRYPOINT ["/usr/bin/tini", "-s", "--"]
CMD ["/opt/scripts/start.sh"]
