// Light Leak: warm drifting light from the edges (screen blend). params: amount, speed
vec4 effect(vec2 uv) {
  vec4 c = getColor(uv);
  float t = time * speed * 0.35;
  vec2 p1 = vec2(-0.1 + 0.25 * sin(t), 0.8 + 0.2 * cos(t * 1.3));
  vec2 p2 = vec2(1.1 + 0.2 * cos(t * 0.7), 0.15 + 0.25 * sin(t * 0.9));
  vec2 a = vec2(srcRatio, 1.0) / max(srcRatio, 1.0);
  float g1 = exp(-dot((uv - p1) * a, (uv - p1) * a) * 5.0);
  float g2 = exp(-dot((uv - p2) * a, (uv - p2) * a) * 6.5);
  vec3 leak = g1 * vec3(1.0, 0.45, 0.15) + g2 * vec3(1.0, 0.3, 0.45);
  leak *= amount * (0.85 + 0.15 * sin(t * 3.1));
  return vec4(1.0 - (1.0 - c.rgb) * (1.0 - clamp(leak, 0.0, 1.0)), c.a);
}
