// Fade Through Blur: both shots blur toward the middle of the transition while dissolving.
vec4 blurFrom(vec2 uv, float r) {
  vec4 acc = vec4(0.0);
  for (int i = 0; i < 24; i++) {
    float a = float(i) * 2.39996;                 // golden angle spiral
    float d = sqrt(float(i) / 24.0) * r;
    acc += getFromColor(uv + vec2(cos(a), sin(a)) * d * px);
  }
  return acc / 24.0;
}
vec4 blurTo(vec2 uv, float r) {
  vec4 acc = vec4(0.0);
  for (int i = 0; i < 24; i++) {
    float a = float(i) * 2.39996;
    float d = sqrt(float(i) / 24.0) * r;
    acc += getToColor(uv + vec2(cos(a), sin(a)) * d * px);
  }
  return acc / 24.0;
}
vec4 transition(vec2 uv) {
  float r = 36.0 * sin(progress * 3.14159265);
  return mix(blurFrom(uv, r), blurTo(uv, r), smoothstep(0.2, 0.8, progress));
}
