// Letterbox: cinema bars top and bottom. params: size (bar height as a fraction of the clip)
vec4 effect(vec2 uv) {
  vec4 c = getColor(uv);
  float bar = step(uv.y, size) + step(1.0 - size, uv.y);
  return vec4(mix(c.rgb, vec3(0.0), min(bar, 1.0)), c.a);
}
