// Circle Iris: B appears inside a growing circle from the center (soft 1% edge).
vec4 transition(vec2 uv) {
  vec2 d = (uv - 0.5) * vec2(ratio, 1.0);
  float maxR = length(vec2(ratio, 1.0)) * 0.5;
  float r = progress * maxR;
  float m = 1.0 - smoothstep(r - 0.01, r, length(d));
  return mix(getFromColor(uv), getToColor(uv), m);
}
