#!/usr/bin/env python3
"""Validate that SageAttention can import and execute on the active CUDA device."""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Run a tiny CUDA kernel smoke test.")
    args = parser.parse_args()

    try:
        import torch
        from sageattention import sageattn
    except Exception as exc:  # noqa: BLE001 - report import/ABI failures clearly to shell caller.
        print(f"SageAttention import failed: {exc}", file=sys.stderr)
        return 1

    print(f"PyTorch: {torch.__version__}")
    print(f"CUDA runtime reported by PyTorch: {torch.version.cuda}")

    if not args.smoke:
        return 0

    if not torch.cuda.is_available():
        print("CUDA is not available; SageAttention cannot be smoke-tested.", file=sys.stderr)
        return 1

    device_name = torch.cuda.get_device_name(0)
    capability = torch.cuda.get_device_capability(0)
    print(f"CUDA device: {device_name} sm_{capability[0]}{capability[1]}")

    try:
        q = torch.randn((1, 1, 16, 64), device="cuda", dtype=torch.float16)
        k = torch.randn((1, 1, 16, 64), device="cuda", dtype=torch.float16)
        v = torch.randn((1, 1, 16, 64), device="cuda", dtype=torch.float16)
        out = sageattn(q, k, v, tensor_layout="HND", is_causal=False)
        torch.cuda.synchronize()
    except Exception as exc:  # noqa: BLE001 - CUDA kernel failures must disable auto mode.
        print(f"SageAttention CUDA smoke test failed: {exc}", file=sys.stderr)
        return 1

    if out.shape != q.shape:
        print(f"SageAttention returned unexpected shape: {tuple(out.shape)}", file=sys.stderr)
        return 1

    print("SageAttention CUDA smoke test OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
