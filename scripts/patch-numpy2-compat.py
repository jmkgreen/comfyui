#!/usr/bin/env python3
"""Patch known third-party NumPy 2 compatibility issues after pip installs."""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPLACEMENTS = {
    "np.Inf": "np.inf",
    "np.Infinity": "np.inf",
    "np.PINF": "np.inf",
    "np.NINF": "-np.inf",
}


def patch_package(package_name: str) -> int:
    spec = importlib.util.find_spec(package_name)
    if spec is None or spec.origin is None:
        print(f"{package_name}: not installed; skipping")
        return 0

    package_root = Path(spec.origin).parent
    patched = 0
    for path in package_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        updated = text
        for old, new in REPLACEMENTS.items():
            updated = updated.replace(old, new)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            patched += 1

    print(f"{package_name}: patched {patched} files under {package_root}")
    return patched


def main() -> int:
    patch_package("gpytoolbox")

    import numpy as np
    import gpytoolbox

    print(f"NumPy: {np.__version__}; gpytoolbox import OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
