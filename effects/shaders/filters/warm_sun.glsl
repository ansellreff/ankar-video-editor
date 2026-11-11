// Warm Taiwan Sun: golden highlights, gently lifted warm shadows, a touch more saturation.
vec4 effect(vec2 uv) {
  vec4 src = getColor(uv);
  vec3 c = src.rgb;
  float l = luma(c);
  vec3 g = c;
  g += vec3(0.06, 0.025, -0.05);                                   // overall warmth
  g = mix(g, g * vec3(1.08, 1.0, 0.86), smoothstep(0.4, 1.0, l));  // golden highlights
  g += vec3(0.03, 0.015, 0.0) * (1.0 - l);                          // warm lift in shadows
  g = mix(vec3(luma(g)), g, 1.12);
  g = (g - 0.5) * 1.04 + 0.5;
  return vec4(mix(c, clamp(g, 0.0, 1.0), amount), src.a);
}
