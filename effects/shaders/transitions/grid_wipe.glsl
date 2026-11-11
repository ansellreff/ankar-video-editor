// Grid Wipe: B appears in squares that pop open in a staggered, random order.
vec4 transition(vec2 uv) {
  float n = 7.0;
  vec2 g = ratio < 1.0 ? vec2(n, floor(n / ratio)) : vec2(floor(n * ratio), n);   // square cells
  vec2 cell = floor(uv * g);
  vec2 f = fract(uv * g) - 0.5;
  float delay = rand(cell + 3.7) * 0.6;
  float lp = clamp((progress - delay) / 0.4, 0.0, 1.0);
  float inside = step(max(abs(f.x), abs(f.y)), lp * 0.5 + 0.001);
  return mix(getFromColor(uv), getToColor(uv), lp >= 1.0 ? 1.0 : inside);
}
