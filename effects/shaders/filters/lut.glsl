// 3D LUT (.cube) with trilinear GPU sampling. u_lut / lutSize are bound by the renderer (gl.py / gfx.js).
uniform highp sampler3D u_lut;
uniform float lutSize;

vec4 effect(vec2 uv) {
  vec4 c = getColor(uv);
  vec3 rgb = c.a > 0.0001 ? c.rgb / c.a : c.rgb;
  float n = max(lutSize, 2.0);
  vec3 coord = clamp(rgb, 0.0, 1.0) * ((n - 1.0) / n) + 0.5 / n;   // texel centers
  vec3 graded = texture(u_lut, coord).rgb;
  rgb = mix(rgb, graded, amount);
  return vec4(rgb * c.a, c.a);
}
