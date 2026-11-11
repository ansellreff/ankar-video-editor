// Posterize: flat color bands. params: levels, amount
vec4 effect(vec2 uv) {
  vec4 c = getColor(uv);
  float n = max(levels, 2.0);
  vec3 q = floor(c.rgb * n + 0.5) / n;
  return vec4(mix(c.rgb, q, amount), c.a);
}
