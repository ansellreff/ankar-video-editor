// Duotone: shadows and highlights mapped to two colors from one hue. params: amount, hue (0..1)
vec3 hsv2rgb(vec3 c) {
  vec3 p = abs(fract(c.xxx + vec3(1.0, 2.0 / 3.0, 1.0 / 3.0)) * 6.0 - 3.0);
  return c.z * mix(vec3(1.0), clamp(p - 1.0, 0.0, 1.0), c.y);
}
vec4 effect(vec2 uv) {
  vec4 c = getColor(uv);
  float y = smoothstep(0.05, 0.95, luma(c.rgb));
  vec3 dark = hsv2rgb(vec3(hue, 0.85, 0.28));
  vec3 light = hsv2rgb(vec3(fract(hue + 0.42), 0.55, 1.0));
  return vec4(mix(c.rgb, mix(dark, light, y), amount), c.a);
}
