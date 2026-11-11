// Split Doors: A splits down the middle and both halves slide out; B settles behind.
vec4 transition(vec2 uv) {
  float p = progress * progress * (3.0 - 2.0 * progress);
  float s = p * 0.5;
  vec2 ub = 0.5 + (uv - 0.5) / (1.08 - 0.08 * p);
  vec4 b = getToColor(ub) * (0.6 + 0.4 * p);
  if (uv.x < 0.5 - s) return getFromColor(vec2(uv.x + s, uv.y));
  if (uv.x > 0.5 + s) return getFromColor(vec2(uv.x - s, uv.y));
  return vec4(b.rgb, 1.0);
}
