// Color Pop: keep one hue, everything else black & white. params: hue (0..1), width, amount
float hueOf(vec3 c) {
  float mx = max(c.r, max(c.g, c.b)), mn = min(c.r, min(c.g, c.b)), d = mx - mn + 1e-5;
  float h = mx == c.r ? mod((c.g - c.b) / d, 6.0) : mx == c.g ? (c.b - c.r) / d + 2.0 : (c.r - c.g) / d + 4.0;
  return h / 6.0;
}
vec4 effect(vec2 uv) {
  vec4 c = getColor(uv);
  float mx = max(c.r, max(c.g, c.b)), mn = min(c.r, min(c.g, c.b));
  float s = (mx - mn) / (mx + 1e-5);
  float dh = abs(hueOf(c.rgb) - hue);
  dh = min(dh, 1.0 - dh);
  float keep = (1.0 - smoothstep(width, width * 1.6, dh)) * smoothstep(0.12, 0.3, s);
  vec3 g = vec3(luma(c.rgb));
  return vec4(mix(c.rgb, mix(g, c.rgb, keep), amount), c.a);
}
