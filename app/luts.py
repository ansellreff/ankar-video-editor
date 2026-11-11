"""3D LUTs (.cube): parse / write / list. Files live in library/luts/ (drop your own .cube files there too).

Layout: data[b][g][r] (red changes fastest, as in the .cube format) = the order a 3D texture expects (x=r, y=g, z=b).
The shader samples at c*(N-1)/N + 0.5/N (texel centers) with trilinear filtering on both renderers.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from .paths import LUTS, ROOT, rel

LUT_DIR = LUTS                           # library/luts (shared by all projects)


def parse_cube(path: Path) -> tuple[int, np.ndarray]:
    """→ (N, float32 array (N, N, N, 3) indexed [b, g, r]), values mapped to 0..1 using DOMAIN_MIN/MAX."""
    n, rows = None, []
    dmin, dmax = np.zeros(3, np.float32), np.ones(3, np.float32)
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        up = s.upper()
        if up.startswith("LUT_3D_SIZE"):
            n = int(s.split()[1])
        elif up.startswith("DOMAIN_MIN"):
            dmin = np.array([float(v) for v in s.split()[1:4]], np.float32)
        elif up.startswith("DOMAIN_MAX"):
            dmax = np.array([float(v) for v in s.split()[1:4]], np.float32)
        elif up.startswith(("TITLE", "LUT_1D_SIZE", "LUT_3D_INPUT_RANGE")):
            if up.startswith("LUT_1D_SIZE"):
                raise ValueError("1D LUTs aren't supported (use a 3D .cube)")
            continue
        elif s[0] in "-.0123456789":
            parts = s.split()
            if len(parts) >= 3:
                rows.append((float(parts[0]), float(parts[1]), float(parts[2])))
    if not n or len(rows) != n ** 3:
        raise ValueError(f"not a valid 3D .cube ({len(rows)} rows for size {n})")
    data = np.array(rows, np.float32).reshape(n, n, n, 3)
    data = (data - dmin) / np.maximum(dmax - dmin, 1e-6)
    return n, np.clip(data, 0.0, 1.0)


def write_cube(path: Path, data: np.ndarray, title: str):
    n = data.shape[0]
    lines = [f'TITLE "{title}"', f"LUT_3D_SIZE {n}", "DOMAIN_MIN 0 0 0", "DOMAIN_MAX 1 1 1"]
    lines += [f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in data.reshape(-1, 3)]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def identity(n=33) -> np.ndarray:
    v = np.linspace(0, 1, n, dtype=np.float32)
    b, g, r = np.meshgrid(v, v, v, indexing="ij")
    return np.stack([r, g, b], -1)


@lru_cache(maxsize=64)
def _load(path: str, mtime: float):
    return parse_cube(Path(path))


def load(file: str) -> tuple[int, np.ndarray]:
    p = ROOT / file
    return _load(str(p), p.stat().st_mtime)


def apply(data: np.ndarray, rgb: np.ndarray) -> np.ndarray:
    """CPU trilinear lookup (for swatches/tests): rgb float (..., 3) in 0..1."""
    n = data.shape[0]
    x = np.clip(rgb, 0, 1) * (n - 1)
    i0 = np.floor(x).astype(int).clip(0, n - 2)
    f = x - i0
    out = 0
    for dr in (0, 1):
        for dg in (0, 1):
            for db in (0, 1):
                w = (f[..., 0] if dr else 1 - f[..., 0]) * (f[..., 1] if dg else 1 - f[..., 1]) * (f[..., 2] if db else 1 - f[..., 2])
                out = out + w[..., None] * data[i0[..., 2] + db, i0[..., 1] + dg, i0[..., 0] + dr]
    return out


SWATCH_IN = np.array([[0.12, 0.12, 0.14], [0.85, 0.62, 0.48], [0.35, 0.55, 0.85], [0.5, 0.5, 0.5], [0.95, 0.93, 0.9]], np.float32)


def list_luts() -> list[dict]:
    """[{name, file, size, swatch:[hex...]}] for library/luts/*.cube (swatch = dark, skin, sky, gray, white through the LUT)."""
    LUT_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(LUT_DIR.glob("*.cube"), key=lambda p: p.name.lower()):
        try:
            n, data = load(rel(p))
        except Exception as e:  # noqa: BLE001 - a broken file shouldn't hide the others
            out.append({"name": p.stem, "file": rel(p), "error": str(e)})
            continue
        sw = (apply(data, SWATCH_IN) * 255).round().astype(int)
        with open(p, encoding="utf-8", errors="replace") as fh:
            head = fh.read(600)
        title = next((ln.split('"')[1] for ln in head.splitlines()[:5]
                      if ln.upper().startswith("TITLE") and ln.count('"') >= 2), None)
        out.append({"name": title or p.stem.replace("_", " "), "file": rel(p), "size": n,
                    "swatch": ["#%02x%02x%02x" % tuple(c) for c in sw]})
    return out
