// Cross Warp: a morph-like sweep — A stretches away left to right as B unfolds into place.
vec4 transition(vec2 uv) {
  float x = smoothstep(0.0, 1.0, progress * 1.6 - 0.3 + (uv.x - 0.5) * 0.6);
  vec2 ua = 0.5 + (uv - 0.5) * (1.0 - 0.35 * x);
  vec2 ub = 0.5 + (uv - 0.5) * (0.65 + 0.35 * x);
  return mix(getFromColor(ua), getToColor(ub), x);
}
