// Old Film: warm monochrome, flicker, scratches, dust and vignette. params: amount
vec4 effect(vec2 uv) {
  vec4 c = getColor(uv);
  float f = floor(time * 24.0);
  float y = luma(c.rgb);
  vec3 tone = vec3(y * 1.08 + 0.03, y * 0.97 + 0.01, y * 0.78);
  tone *= 0.92 + 0.16 * rand(vec2(f, 1.7));                      // flicker
  for (int k = 0; k < 3; k++) {                                   // vertical scratches
    float sx = rand(vec2(float(k) * 3.1, floor(time * 6.0)));
    float on = step(0.45, rand(vec2(f, float(k))));
    tone += on * 0.35 * smoothstep(px.x * 1.5, 0.0, abs(uv.x - sx));
  }
  vec2 cell = floor(uv / (px * 6.0));
  float dust = step(0.9985, rand(cell + f));
  tone = mix(tone, vec3(0.05), dust);
  vec2 d = uv - 0.5;
  tone *= 1.0 - dot(d, d) * 1.2;
  return vec4(mix(c.rgb, clamp(tone, 0.0, 1.0), amount), c.a);
}
