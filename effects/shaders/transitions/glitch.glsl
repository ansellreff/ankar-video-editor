// Glitch: blocky horizontal displacement + RGB split that peaks at the cut.
vec4 transition(vec2 uv) {
  float k = 1.0 - abs(progress * 2.0 - 1.0);                  // 0 → 1 → 0
  float step_t = floor(progress * 18.0);                      // flicker rate
  float band = floor(uv.y * 24.0);
  float r = rand(vec2(band, step_t));
  float shift = (r > 0.55 ? (r - 0.55) * 0.5 : 0.0) * k;
  vec2 u = vec2(fract(uv.x + shift * (rand(vec2(step_t, band)) > 0.5 ? 1.0 : -1.0)), uv.y);
  float split = 0.012 * k;
  bool useB = progress > 0.5;
  vec4 cr = useB ? getToColor(u + vec2(split, 0.0)) : getFromColor(u + vec2(split, 0.0));
  vec4 cg = useB ? getToColor(u) : getFromColor(u);
  vec4 cb = useB ? getToColor(u - vec2(split, 0.0)) : getFromColor(u - vec2(split, 0.0));
  return vec4(cr.r, cg.g, cb.b, cg.a);
}
