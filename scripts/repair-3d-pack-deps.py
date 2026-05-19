#!/usr/bin/env python3
"""Repair ComfyUI-3D-Pack binary dependencies for the image Torch stack."""

from __future__ import annotations

import subprocess
import sys


def torch_cuda_tag() -> tuple[str, str]:
    import torch

    torch_version = torch.__version__.split("+", 1)[0]
    cuda_version = torch.version.cuda
    if not cuda_version:
        raise RuntimeError("Torch does not report a CUDA version")

    return torch_version, "cu" + cuda_version.replace(".", "")


def main() -> int:
    torch_version, cuda_tag = torch_cuda_tag()
    pyg_wheel_url = f"https://data.pyg.org/whl/torch-{torch_version}+{cuda_tag}.html"

    print(f"Repairing torch-scatter for torch {torch_version} / {cuda_tag}")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--force-reinstall",
            "--no-deps",
            "torch-scatter",
            "--find-links",
            pyg_wheel_url,
        ],
        check=True,
    )

    import torch
    import torch_scatter

    print(f"Torch: {torch.__version__}; torch_scatter import OK")
    print(f"torch_scatter: {getattr(torch_scatter, '__version__', 'unknown')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
