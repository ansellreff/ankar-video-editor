// Flash: a bright exposure flash that peaks mid-way, cut hidden inside it.
vec4 transition(vec2 uv) {
  float f = pow(1.0 - abs(progress * 2.0 - 1.0), 2.0);
  vec4 c = mix(getFromColor(uv), getToColor(uv), smoothstep(0.45, 0.55, progress));
  return vec4(mix(c.rgb, vec3(1.0, 0.97, 0.9), f * 0.95), max(c.a, f));
}
