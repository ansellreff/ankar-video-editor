// Whip Pan: fast push with heavy directional motion blur. params: direction (0 →, 1 ←, 2 ↓, 3 ↑)
vec2 whipDir() {
  if (direction < 0.5) return vec2(1.0, 0.0);
  if (direction < 1.5) return vec2(-1.0, 0.0);
  if (direction < 2.5) return vec2(0.0, -1.0);
  return vec2(0.0, 1.0);
}
vec4 sampleAt(vec2 uv, float p, vec2 dir) {
  vec2 a = uv - dir * p;
  vec2 b = uv - dir * (p - 1.0);
  if (a.x >= 0.0 && a.x <= 1.0 && a.y >= 0.0 && a.y <= 1.0) return getFromColor(a);
  return getToColor(fract(b));
}
vec4 transition(vec2 uv) {
  float p = progress < 0.5 ? 4.0 * progress * progress * progress : 1.0 - pow(-2.0 * progress + 2.0, 3.0) / 2.0;
  vec2 dir = whipDir();
  float blur = 0.18 * sin(progress * 3.14159265);
  vec4 acc = vec4(0.0);
  for (int i = 0; i < 20; i++) {
    float o = (float(i) / 19.0 - 0.5) * blur;
    acc += sampleAt(uv + dir * o, p, dir);
  }
  return acc / 20.0;
}
