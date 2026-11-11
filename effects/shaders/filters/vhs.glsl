// VHS: line jitter, color bleed, scanlines, noise and a rolling tracking band. params: amount
// Patterns sit on a 4-reference-pixel grid so the half-size preview and the full-size export match.
vec4 effect(vec2 uv) {
  float f = floor(time * 30.0);
  float line = floor(uv.y / (px.y * 4.0));
  float jit = (rand(vec2(line, f)) - 0.5) * 0.004 * amount;
  float band = smoothstep(0.06, 0.0, abs(fract(uv.y - time * 0.13) - 0.5) - 0.42);
  jit += band * (rand(vec2(f, line)) - 0.3) * 0.02 * amount;
  vec2 u = vec2(uv.x + jit, uv.y);
  float sp = px.x * 6.0 * amount;
  vec3 col = vec3(getColor(u + vec2(sp, 0.0)).r, getColor(u).g, getColor(u - vec2(sp, 0.0)).b);
  float a = getColor(uv).a;
  col = mix(col, vec3(luma(col)), 0.25 * amount);
  col *= 1.0 - 0.18 * amount * step(0.5, fract(uv.y / (px.y * 8.0)));
  col += (rand(floor(uv / (px * 4.0)) + f * 1.37) - 0.5) * 0.12 * amount;
  col += band * 0.12 * amount;
  col = mix(col, col * vec3(1.05, 0.98, 1.08), amount);
  return vec4(clamp(col, 0.0, 1.0) * a, a);
}
