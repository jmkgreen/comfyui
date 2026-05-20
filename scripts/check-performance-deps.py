#!/usr/bin/env python3
"""Print the availability of optional ComfyUI acceleration packages."""

from __future__ import annotations

import importlib.util


PACKAGES = {
    "sageattention": "SageAttention",
    "xformers": "xFormers",
    "flash_attn": "FlashAttention",
}


def main() -> int:
    torch_spec = importlib.util.find_spec("torch")
    if torch_spec:
        import torch

        print(f"PyTorch: {torch.__version__}")
        print(f"CUDA runtime reported by PyTorch: {torch.version.cuda}")
    else:
        print("PyTorch: missing")

    for module_name, display_name in PACKAGES.items():
        status = "available" if importlib.util.find_spec(module_name) else "missing"
        print(f"{display_name}: {status}")

    print("Run /opt/scripts/check-sage-attention.py --smoke to verify SageAttention kernels on this GPU.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
