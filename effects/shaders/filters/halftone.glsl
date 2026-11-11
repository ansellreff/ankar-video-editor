// Halftone: printed-dot look on a 45° grid. params: size (px), amount
vec4 effect(vec2 uv) {
  vec4 c = getColor(uv);
  vec2 p = uv / px;                                   // reference pixels
  float s = max(size, 2.0);
  mat2 rot = mat2(0.7071, -0.7071, 0.7071, 0.7071);
  vec2 q = rot * p / s;
  vec2 cell = floor(q) + 0.5;
  vec2 center = transpose(rot) * (cell * s) * px;
  vec3 cc = getColor(center).rgb;
  float r = sqrt(1.0 - luma(cc)) * 0.72;
  float d = length(q - cell);
  float ink = 1.0 - smoothstep(r - 0.06, r + 0.06, d);
  vec3 paper = mix(cc, vec3(1.0), 0.45);
  vec3 col = mix(paper, cc * 0.3, ink);
  return vec4(mix(c.rgb, col, amount), c.a);
}
