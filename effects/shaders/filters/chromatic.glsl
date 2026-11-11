// Chromatic Aberration: red/blue fringes that grow toward the edges. param: amount (px at the corners)
vec4 effect(vec2 uv) {
  vec2 d = uv - 0.5;
  vec2 o = d * (length(d) / 0.7071) * amount * px / max(length(d), 1e-4);
  float r = getColor(uv + o).r;
  vec4 g = getColor(uv);
  float b = getColor(uv - o).b;
  return vec4(r, g.g, b, g.a);
}
