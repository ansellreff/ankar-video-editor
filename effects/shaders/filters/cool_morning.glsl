// Cool Morning: crisp blue-ish air, slightly desaturated, soft blue lift in the blacks.
vec4 effect(vec2 uv) {
  vec4 src = getColor(uv);
  vec3 c = src.rgb;
  vec3 g = c + vec3(-0.05, 0.0, 0.06);
  float l = luma(g);
  g += vec3(0.0, 0.02, 0.05) * (1.0 - smoothstep(0.0, 0.4, l));
  g = mix(vec3(l), g, 0.88);
  g = (g - 0.5) * 1.05 + 0.52;
  return vec4(mix(c, clamp(g, 0.0, 1.0), amount), src.a);
}
