// Ripple: water rings spread from the center while A dissolves into B.
vec4 transition(vec2 uv) {
  float k = sin(progress * 3.14159);
  vec2 d = (uv - 0.5) * vec2(ratio, 1.0);
  float r = length(d);
  float w = sin(r * 60.0 - progress * 25.0) * 0.012 * k * smoothstep(0.9, 0.0, r);
  vec2 u = clamp(uv + normalize(d + 1e-5) / vec2(ratio, 1.0) * w, 0.0, 1.0);
  return mix(getFromColor(u), getToColor(u), smoothstep(0.25, 0.75, progress));
}
