// RGB Split Dissolve: color channels drift apart at the cut, then lock back together on B.
vec4 transition(vec2 uv) {
  float k = sin(progress * 3.14159);
  vec2 o = vec2(0.025 * k, 0.006 * k);
  float m = smoothstep(0.3, 0.7, progress);
  vec4 r = mix(getFromColor(uv + o), getToColor(uv + o), m);
  vec4 g = mix(getFromColor(uv), getToColor(uv), m);
  vec4 b = mix(getFromColor(uv - o), getToColor(uv - o), m);
  return vec4(r.r, g.g, b.b, 1.0);
}
