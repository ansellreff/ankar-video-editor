// Diamond Wipe: B opens from the center in a diamond.
vec4 transition(vec2 uv) {
  vec2 d = abs(uv - 0.5) * vec2(ratio, 1.0) / max(ratio, 1.0);
  float m = d.x + d.y;
  float edge = progress * 1.05;
  return mix(getToColor(uv), getFromColor(uv), smoothstep(edge - 0.01, edge + 0.01, m));
}
