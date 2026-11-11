// Film Burn: a hot orange burn eats through A with a ragged edge, revealing B.
float vn(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(mix(rand(i), rand(i + vec2(1.0, 0.0)), f.x), mix(rand(i + vec2(0.0, 1.0)), rand(i + 1.0), f.x), f.y);
}
vec4 transition(vec2 uv) {
  vec2 d = (uv - vec2(0.62, 0.42)) * vec2(ratio, 1.0);
  float n = vn(uv * 6.0) * 0.6 + vn(uv * 17.0) * 0.4;
  float r = length(d) + (n - 0.5) * 0.35;
  float front = progress * 1.6 - 0.1;
  float e = r - front;
  vec4 a = getFromColor(uv), b = getToColor(uv);
  vec3 burn = mix(vec3(1.0, 0.95, 0.75), vec3(1.0, 0.35, 0.05), smoothstep(0.0, 0.12, abs(e)));
  float glow = 1.0 - smoothstep(0.0, 0.16, abs(e));
  vec3 col = e > 0.0 ? a.rgb * (1.0 - glow * 0.6) : b.rgb;
  col = mix(col, burn, glow * (1.0 - smoothstep(0.85, 1.0, progress)));
  return vec4(col, 1.0);
}
