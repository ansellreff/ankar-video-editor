// Faded Matte: lifted blacks, softened whites, lower contrast, slightly muted.
vec4 effect(vec2 uv) {
  vec4 src = getColor(uv);
  vec3 c = src.rgb;
  vec3 g = c * 0.82 + 0.1;
  float l = luma(g);
  g = mix(vec3(l), g, 0.85);
  g += vec3(0.01, 0.0, 0.02);
  return vec4(mix(c, clamp(g, 0.0, 1.0), amount), src.a);
}
