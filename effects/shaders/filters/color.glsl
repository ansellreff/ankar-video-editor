// Basic color correction (Lumetri-lite). All params neutral at their defaults.
vec4 effect(vec2 uv) {
  vec4 src = getColor(uv);
  vec3 c = src.rgb;
  c *= pow(2.0, exposure);                                         // exposure in stops
  float l = luma(c);
  c += shadows * 0.35 * (1.0 - smoothstep(0.0, 0.5, l)) * (1.0 - l);   // lift/crush shadows
  c += highlights * 0.35 * smoothstep(0.5, 1.0, l) * l;                // recover/boost highlights
  c = (c - 0.5) * (1.0 + contrast) + 0.5;                              // contrast around mid-grey
  c += vec3(temperature * 0.08, temperature * 0.01, -temperature * 0.08);  // warm/cool
  c += vec3(tint * 0.04, -tint * 0.06, tint * 0.04);                   // magenta/green
  l = luma(c);
  float sat = max(max(c.r, c.g), c.b) - min(min(c.r, c.g), c.b);
  float vib = 1.0 + vibrance * (1.0 - sat);                           // vibrance: boost muted colors most
  c = mix(vec3(l), c, saturation * vib);
  return vec4(clamp(c, 0.0, 1.0), src.a);
}
