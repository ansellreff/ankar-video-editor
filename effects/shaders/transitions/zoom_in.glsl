// Zoom In: A rushes toward the camera and dissolves into B, which settles from a slight zoom.
vec4 transition(vec2 uv) {
  float p = smoothstep(0.0, 1.0, progress);
  vec2 c = vec2(0.5);
  vec2 ua = c + (uv - c) / (1.0 + p * 1.6);
  vec2 ub = c + (uv - c) / (1.0 + (1.0 - p) * 0.35);
  vec4 a = vec4(0.0);
  vec4 b = vec4(0.0);
  for (int i = 0; i < 10; i++) {                  // radial zoom blur
    float k = float(i) / 9.0;
    a += getFromColor(c + (ua - c) * (1.0 - k * 0.08 * p));
    b += getToColor(c + (ub - c) * (1.0 - k * 0.05 * (1.0 - p)));
  }
  return mix(a / 10.0, b / 10.0, smoothstep(0.35, 0.75, progress));
}
