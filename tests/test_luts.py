import numpy as np
import pytest

from app import luts


def test_cube_roundtrip_and_domain(tmp_path):
    data = luts.identity(5)
    data[..., 0] = data[..., 0] ** 2
    p = tmp_path / "t.cube"
    luts.write_cube(p, data, "Test")
    n, back = luts.parse_cube(p)
    assert n == 5 and np.allclose(back, data, atol=1e-5)
    p.write_text("LUT_3D_SIZE 2\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 2 2 2\n" + "\n".join(["0 0 0", "2 0 0", "0 2 0", "2 2 0", "0 0 2", "2 0 2", "0 2 2", "2 2 2"]))
    n, d = luts.parse_cube(p)
    assert d.max() == 1.0 and np.allclose(d[0, 0, 1], [1, 0, 0])                      # red fastest → [b, g, r]
    p.write_text("LUT_3D_SIZE 3\n0 0 0\n")
    with pytest.raises(ValueError):
        luts.parse_cube(p)


def test_identity_cpu_lookup():
    rgb = np.random.default_rng(0).random((100, 3)).astype(np.float32)
    assert np.allclose(luts.apply(luts.identity(17), rgb), rgb, atol=1e-5)


def test_builtin_pack_present():
    names = {l["name"] for l in luts.list_luts()}
    assert {"Teal & Orange", "Warm Film", "Bleach Bypass", "Night Neon", "Crisp Travel"} <= names
    assert len([l for l in luts.list_luts() if not l.get("error")]) >= 12


def _gpu_lut(file, amount, img):
    """Run lut.glsl through the export renderer on an RGB uint8 image."""
    from app.render.gl import GL
    g = GL()
    h, w = img.shape[:2]
    src = g.upload(np.dstack([img, np.full((h, w), 255, np.uint8)]), slot="src")
    g.filter_pass(src, w, h, "filters/lut.glsl", {"amount": amount}, 0.0, "f0", lut=file)
    fbo, _ = g.fbo(w, h, "f0")
    return g.read_rgb(fbo, w, h)


def test_gpu_identity_and_real_look(tmp_path):
    from app.paths import ROOT, rel
    rng = np.random.default_rng(1)
    img = rng.integers(0, 256, (32, 48, 3), dtype=np.uint8)
    ident = ROOT / "cache" / "test_identity.cube"
    ident.parent.mkdir(exist_ok=True)
    luts.write_cube(ident, luts.identity(33), "Identity")
    out = _gpu_lut(rel(ident), 1.0, img)
    assert np.abs(out.astype(int) - img).max() <= 1                                     # identity LUT changes nothing
    teal = next(l for l in luts.list_luts() if l["name"] == "Teal & Orange")["file"]
    graded = _gpu_lut(teal, 1.0, img)
    ref = luts.apply(luts.load(teal)[1], img / 255.0) * 255
    assert np.abs(graded - ref).mean() < 1.5                                             # GPU trilinear ≈ CPU reference
    half = _gpu_lut(teal, 0.5, img)
    assert np.abs(half - (img * 0.5 + graded * 0.5)).mean() < 1.5                        # amount mixes
    ident.unlink()
