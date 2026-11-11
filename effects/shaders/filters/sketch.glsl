// Sketch: pencil lines from edges on paper. params: amount, strength
// Edges come from a lightly smoothed luma and ignore very weak gradients, so compression blocks in the preview proxy
// don't draw lines that the original footage doesn't have.
float sl(vec2 uv) {
  vec2 h = px * 1.0;
  return 0.25 * (luma(getColor(uv + vec2(h.x, h.y)).rgb) + luma(getColor(uv + vec2(-h.x, h.y)).rgb)
               + luma(getColor(uv + vec2(h.x, -h.y)).rgb) + luma(getColor(uv - h).rgb));
}
vec4 effect(vec2 uv) {
  vec4 c = getColor(uv);
  vec2 o = px * 2.5;
  float tl = sl(uv + vec2(-o.x, o.y)), t = sl(uv + vec2(0.0, o.y)), tr = sl(uv + o);
  float l = sl(uv - vec2(o.x, 0.0)), r = sl(uv + vec2(o.x, 0.0));
  float bl = sl(uv - o), b = sl(uv - vec2(0.0, o.y)), br = sl(uv + vec2(o.x, -o.y));
  float gx = -tl - 2.0 * l - bl + tr + 2.0 * r + br;
  float gy = -bl - 2.0 * b - br + tl + 2.0 * t + tr;
  float e = clamp((length(vec2(gx, gy)) - 0.06) * strength, 0.0, 1.0);
  float paper = 0.96 - 0.04 * rand(floor(uv / (px * 4.0)));
  vec3 col = vec3(paper * (1.0 - e)) * mix(vec3(1.0), vec3(1.0, 0.98, 0.94), 0.6);
  col = mix(col, col * (0.85 + 0.15 * luma(c.rgb)), 0.5);
  return vec4(mix(c.rgb, col, amount), c.a);
}
