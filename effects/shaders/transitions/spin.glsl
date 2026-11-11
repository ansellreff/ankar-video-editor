// Spin: A spins and shrinks away, B spins in from the other side.
vec2 spinUV(vec2 uv, float ang, float scale) {
  vec2 d = (uv - 0.5) * vec2(ratio, 1.0);
  d = mat2(cos(ang), sin(ang), -sin(ang), cos(ang)) * d / scale;
  return d / vec2(ratio, 1.0) + 0.5;
}
vec4 sampleIn(vec2 u, bool to) {
  if (u.x < 0.0 || u.x > 1.0 || u.y < 0.0 || u.y > 1.0) return vec4(0.0, 0.0, 0.0, 1.0);
  return to ? getToColor(u) : getFromColor(u);
}
vec4 transition(vec2 uv) {
  float p = smoothstep(0.0, 1.0, progress);
  vec4 a = sampleIn(spinUV(uv, p * 3.14159, 1.0 - 0.7 * p), false);
  vec4 b = sampleIn(spinUV(uv, (p - 1.0) * 3.14159, 0.3 + 0.7 * p), true);
  return mix(a, b, smoothstep(0.35, 0.65, progress));
}
