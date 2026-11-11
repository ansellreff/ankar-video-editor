// Push: B pushes A out of frame. params: direction (0 →, 1 ←, 2 ↓, 3 ↑)
vec2 pushDir() {
  if (direction < 0.5) return vec2(1.0, 0.0);
  if (direction < 1.5) return vec2(-1.0, 0.0);
  if (direction < 2.5) return vec2(0.0, -1.0);
  return vec2(0.0, 1.0);
}
vec4 transition(vec2 uv) {
  float p = progress * progress * (3.0 - 2.0 * progress);   // ease in-out
  vec2 dir = pushDir();
  vec2 a = uv - dir * p;            // where A is sampled
  vec2 b = uv - dir * (p - 1.0);    // B comes in from the opposite side
  if (a.x >= 0.0 && a.x <= 1.0 && a.y >= 0.0 && a.y <= 1.0) return getFromColor(a);
  return getToColor(b);
}
