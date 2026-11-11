// Zoom Out: A pulls away into the distance while B lands from close-up.
vec4 transition(vec2 uv) {
  float p = smoothstep(0.0, 1.0, progress);
  vec2 c = vec2(0.5);
  vec2 ua = c + (uv - c) * (1.0 + p * 1.4);
  vec2 ub = c + (uv - c) * (0.55 + 0.45 * p);
  vec4 a = vec4(0.0), b = vec4(0.0);
  for (int i = 0; i < 8; i++) {
    float k = float(i) / 7.0;
    a += getFromColor(clamp(c + (ua - c) * (1.0 + k * 0.06 * p), 0.0, 1.0));
    b += getToColor(clamp(c + (ub - c) * (1.0 - k * 0.06 * (1.0 - p)), 0.0, 1.0));
  }
  vec4 A = (ua.x < 0.0 || ua.x > 1.0 || ua.y < 0.0 || ua.y > 1.0) ? vec4(0.0, 0.0, 0.0, 1.0) : a / 8.0;
  return mix(A, b / 8.0, smoothstep(0.3, 0.7, progress));
}
