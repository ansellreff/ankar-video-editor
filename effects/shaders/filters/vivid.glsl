// Vivid: punchy color and contrast, protecting already-saturated colors (vibrance-style).
vec4 effect(vec2 uv) {
  vec4 src = getColor(uv);
  vec3 c = src.rgb;
  float l = luma(c);
  float sat = max(max(c.r, c.g), c.b) - min(min(c.r, c.g), c.b);
  vec3 g = mix(vec3(l), c, 1.0 + 0.55 * (1.0 - sat) + 0.15);
  g = (g - 0.5) * 1.12 + 0.5;
  return vec4(mix(c, clamp(g, 0.0, 1.0), amount), src.a);
}
