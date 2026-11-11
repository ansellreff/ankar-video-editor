// Shake Cut: the camera shakes harder and harder, hard cut to B, shake settles.
vec4 transition(vec2 uv) {
  float k = 1.0 - abs(progress * 2.0 - 1.0);
  k = k * k;
  float f = floor(progress * 40.0);
  vec2 off = (vec2(rand(vec2(f, 1.0)), rand(vec2(f, 2.0))) - 0.5) * 0.08 * k;
  vec2 u = clamp(0.5 + (uv - 0.5) / (1.0 + 0.1 * k) + off, 0.0, 1.0);
  vec4 c = vec4(0.0);
  for (int i = 0; i < 5; i++) {                    // motion blur along the shake
    vec2 uu = clamp(u + off * (float(i) / 4.0 - 0.5) * 0.6, 0.0, 1.0);
    c += progress < 0.5 ? getFromColor(uu) : getToColor(uu);
  }
  return c / 5.0;
}
