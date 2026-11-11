// Squeeze: A squeezes to the left edge as B stretches in from the right.
vec4 transition(vec2 uv) {
  float p = progress * progress * (3.0 - 2.0 * progress);
  float e = 1.0 - p;
  if (uv.x < e) return getFromColor(vec2(uv.x / max(e, 1e-4), uv.y));
  return getToColor(vec2((uv.x - e) / max(p, 1e-4), uv.y));
}
