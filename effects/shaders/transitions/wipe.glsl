// Linear wipe. params: direction (0 →, 1 ←, 2 ↓, 3 ↑), softness (edge width, 0 = sharp)
vec4 transition(vec2 uv) {
  float pos;
  if (direction < 0.5)      pos = uv.x;
  else if (direction < 1.5) pos = 1.0 - uv.x;
  else if (direction < 2.5) pos = 1.0 - uv.y;      // uv.y = 0 is the bottom
  else                      pos = uv.y;
  float s = max(softness, 0.0001);
  float edge = progress * (1.0 + s);
  float m = 1.0 - smoothstep(edge - s, edge, pos);
  return mix(getFromColor(uv), getToColor(uv), m);
}
