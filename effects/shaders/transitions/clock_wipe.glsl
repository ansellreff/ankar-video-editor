// Clock Wipe: a hand sweeps clockwise from 12 o'clock revealing B.
vec4 transition(vec2 uv) {
  vec2 d = (uv - 0.5) * vec2(ratio, 1.0);
  float ang = atan(d.x, d.y);                      // 0 at 12 o'clock, clockwise positive
  float t = (ang < 0.0 ? ang + 6.2831853 : ang) / 6.2831853;
  return t < progress ? getToColor(uv) : getFromColor(uv);
}
