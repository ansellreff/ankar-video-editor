// Teal & Orange: teal shadows, orange skin/highlights, a cinematic split tone.
vec4 effect(vec2 uv) {
  vec4 src = getColor(uv);
  vec3 c = src.rgb;
  float l = luma(c);
  vec3 teal = vec3(0.0, 0.35, 0.42);
  vec3 orange = vec3(1.0, 0.62, 0.32);
  vec3 g = c;
  g = mix(g, g * 0.75 + teal * 0.25, (1.0 - smoothstep(0.05, 0.55, l)) * 0.8);
  g = mix(g, g * 0.82 + orange * 0.18, smoothstep(0.45, 0.95, l) * 0.8);
  g = (g - 0.5) * 1.08 + 0.5;
  return vec4(mix(c, clamp(g, 0.0, 1.0), amount), src.a);
}
