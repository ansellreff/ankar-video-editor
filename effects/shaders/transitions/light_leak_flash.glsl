// Light Leak Flash: a warm light leak sweeps across and hides the cut.
vec4 transition(vec2 uv) {
  float k = sin(progress * 3.14159);
  vec2 c = vec2(-0.3 + progress * 1.6, 0.6 + 0.2 * sin(progress * 4.0));
  vec2 a = vec2(ratio, 1.0) / max(ratio, 1.0);
  float g = exp(-dot((uv - c) * a, (uv - c) * a) * 3.0) * k;
  vec3 leak = mix(vec3(1.0, 0.55, 0.2), vec3(1.0, 0.95, 0.85), g) * g * 1.6;
  vec4 base = mix(getFromColor(uv), getToColor(uv), smoothstep(0.35, 0.65, progress));
  return vec4(1.0 - (1.0 - base.rgb) * (1.0 - clamp(leak + k * 0.15, 0.0, 1.0)), 1.0);
}
