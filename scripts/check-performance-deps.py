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
    for module_name, display_name in PACKAGES.items():
        status = "available" if importlib.util.find_spec(module_name) else "missing"
        print(f"{display_name}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
