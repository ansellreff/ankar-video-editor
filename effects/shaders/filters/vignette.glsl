// Vignette: darkens the corners. params: amount, size
vec4 effect(vec2 uv) {
  vec4 c = getColor(uv);
  vec2 d = (uv - 0.5) * vec2(srcRatio, 1.0) / max(srcRatio, 1.0);
  float v = smoothstep(size, size * 0.35, length(d) * 1.2);
  return vec4(c.rgb * mix(1.0, v, amount), c.a);
}
