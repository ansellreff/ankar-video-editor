// Swirl: the picture twists into a whirlpool and untwists as B.
vec4 transition(vec2 uv) {
  float k = sin(progress * 3.14159);
  vec2 d = (uv - 0.5) * vec2(ratio, 1.0);
  float r = length(d);
  float ang = k * 5.0 * max(0.0, 0.8 - r);
  d = mat2(cos(ang), sin(ang), -sin(ang), cos(ang)) * d;
  vec2 u = clamp(d / vec2(ratio, 1.0) + 0.5, 0.0, 1.0);
  return mix(getFromColor(u), getToColor(u), smoothstep(0.4, 0.6, progress));
}
