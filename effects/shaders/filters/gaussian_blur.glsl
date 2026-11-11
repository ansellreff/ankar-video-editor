// Gaussian-like blur (golden-angle spiral, 48 taps, gaussian weights). param: radius (px at 1080x1920)
vec4 effect(vec2 uv) {
  if (radius < 0.5) return getColor(uv);
  vec4 acc = vec4(0.0);
  float wsum = 0.0;
  for (int i = 0; i < 48; i++) {
    float a = float(i) * 2.39996;
    float d = sqrt((float(i) + 0.5) / 48.0);
    float w = exp(-d * d * 2.0);
    acc += getColor(uv + vec2(cos(a), sin(a)) * d * radius * px) * w;
    wsum += w;
  }
  return acc / wsum;
}
