// Lens Fisheye: barrel (+) or pincushion (−) distortion. params: amount (-1..1)
vec4 effect(vec2 uv) {
  vec2 d = (uv - 0.5) * vec2(srcRatio, 1.0);
  float r2 = dot(d, d);
  float k = amount * 0.9;
  vec2 dd = d * (1.0 - k * 0.45) / (1.0 - k * r2 * 0.9);
  vec2 u = dd / vec2(srcRatio, 1.0) + 0.5;
  if (u.x < 0.0 || u.x > 1.0 || u.y < 0.0 || u.y > 1.0) return vec4(0.0, 0.0, 0.0, getColor(uv).a);
  return getColor(u);
}
