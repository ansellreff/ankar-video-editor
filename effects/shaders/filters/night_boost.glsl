// Night Boost: brightens dark street footage (gamma lift), cool shadows, richer neon colors.
vec4 effect(vec2 uv) {
  vec4 src = getColor(uv);
  vec3 c = src.rgb;
  vec3 g = pow(max(c, vec3(0.0)), vec3(0.78));            // lift the darks more than the brights
  float l = luma(g);
  g += vec3(-0.01, 0.0, 0.03) * (1.0 - l);                // cool night shadows
  float sat = max(max(g.r, g.g), g.b) - min(min(g.r, g.g), g.b);
  g = mix(vec3(l), g, 1.2 + 0.2 * sat);                   // neon pop
  return vec4(mix(c, clamp(g, 0.0, 1.0), amount), src.a);
}
