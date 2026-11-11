"""Consistent color handling: decode with the file's own matrix, encode BT.709 and tag it.

Without this, PyAV/swscale converts RGB<->YUV with BT.601 while browsers and phones display untagged HD video
as BT.709, so the same file would look slightly different in the preview, the export and on the phone.
"""
import av
from av.video.reformatter import Colorspace

# AVColorSpace numbers (libavutil/pixfmt.h)
_BT709, _BT470BG, _SMPTE170M = 1, 5, 6

X264_709 = "colorprim=bt709:transfer=bt709:colormatrix=bt709"


def src_colorspace(frame) -> Colorspace:
    cs = int(getattr(frame, "colorspace", 2) or 2)
    if cs == _BT709:
        return Colorspace.ITU709
    if cs in (_BT470BG, _SMPTE170M):
        return Colorspace.ITU601
    # untagged: same convention as browsers/players (HD → 709, SD → 601)
    return Colorspace.ITU709 if (frame.height >= 720 or frame.width >= 1280) else Colorspace.ITU601


def to_rgb(frame, width=None, height=None):
    return frame.reformat(width=width, height=height, format="rgb24", src_colorspace=src_colorspace(frame)).to_ndarray()


def rgb_to_yuv709(arr) -> av.VideoFrame:
    f = av.VideoFrame.from_ndarray(arr, format="rgb24").reformat(format="yuv420p", dst_colorspace=Colorspace.ITU709)
    for attr, val in (("colorspace", _BT709), ("color_primaries", 1), ("color_trc", 1), ("color_range", 1)):
        try:
            setattr(f, attr, val)
        except (AttributeError, TypeError, ValueError):
            pass
    return f


def x264_options(**opts) -> dict:
    """libx264 options with BT.709 VUI tags (so players decode with the matrix we encoded with)."""
    return {**opts, "x264-params": X264_709}
