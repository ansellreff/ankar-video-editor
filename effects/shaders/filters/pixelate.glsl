// Pixelate: mosaic blocks. param: size (px at 1080x1920)
vec4 effect(vec2 uv) {
  vec2 b = px * max(size, 1.0);
  return getColor((floor(uv / b) + 0.5) * b);
}
