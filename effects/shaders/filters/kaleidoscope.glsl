// Mirror / Kaleidoscope. params: mode (0 mirror L→R, 1 mirror top→bottom, 2 four-way, 3 kaleidoscope), segments
vec4 effect(vec2 uv) {
  vec2 u = uv;
  if (mode < 0.5) {
    u.x = 0.5 - abs(uv.x - 0.5);
  } else if (mode < 1.5) {
    u.y = 0.5 + abs(uv.y - 0.5);
  } else if (mode < 2.5) {
    u = 0.5 - abs(uv - 0.5);
  } else {
    vec2 d = (uv - 0.5) * vec2(srcRatio, 1.0);
    float n = max(segments, 2.0);
    float seg = 6.28318 / n;
    float a = atan(d.y, d.x);
    a = mod(a, seg);
    a = abs(a - seg * 0.5);
    float r = length(d);
    u = vec2(cos(a), sin(a)) * r / vec2(srcRatio, 1.0) + 0.5;
  }
  return getColor(clamp(u, 0.0, 1.0));
}
