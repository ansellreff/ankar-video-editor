// Vintage Film: faded warm print, greenish shadows, softened saturation, gentle S-curve.
vec4 effect(vec2 uv) {
  vec4 src = getColor(uv);
  vec3 c = src.rgb;
  vec3 g = c * c * (3.0 - 2.0 * c);                    // S-curve
  g = mix(c, g, 0.5);
  float l = luma(g);
  g = mix(vec3(l), g, 0.72);
  g += vec3(0.05, 0.03, -0.02);                        // warm print
  g += vec3(-0.01, 0.025, 0.0) * (1.0 - l);            // green-ish shadows
  g = g * 0.88 + 0.07;                                 // faded blacks & whites
  return vec4(mix(c, clamp(g, 0.0, 1.0), amount), src.a);
}
