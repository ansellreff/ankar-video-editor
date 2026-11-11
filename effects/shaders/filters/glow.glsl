// Glow / Bloom: bright areas bleed soft light (screen blend). params: amount, radius (px)
vec4 effect(vec2 uv) {
  vec4 c = getColor(uv);
  vec3 acc = vec3(0.0);
  float tot = 0.0;
  for (int j = 1; j <= 3; j++) {
    float r = radius * float(j) / 3.0;
    for (int i = 0; i < 12; i++) {
      float a = float(i) * 0.5236 + float(j) * 0.26;
      vec3 s = getColor(uv + vec2(cos(a), sin(a)) * px * r).rgb;
      float w = 1.0 / float(j);
      acc += max(s - 0.55, 0.0) / 0.45 * w;
      tot += w;
    }
  }
  vec3 g = clamp(acc / tot * amount * 1.6, 0.0, 1.0);
  return vec4(1.0 - (1.0 - c.rgb) * (1.0 - g), c.a);
}
