// Camera Shake: smooth handheld wobble (slightly zoomed so edges never show). params: amount, speed
float vnoise(float t, float seed) {
  float i = floor(t), f = fract(t);
  return mix(rand(vec2(i, seed)), rand(vec2(i + 1.0, seed)), f * f * (3.0 - 2.0 * f)) - 0.5;
}
vec4 effect(vec2 uv) {
  float t = time * speed * 6.0;
  vec2 off = vec2(vnoise(t, 1.3) + 0.5 * vnoise(t * 2.3, 4.1), vnoise(t, 7.7) + 0.5 * vnoise(t * 2.1, 9.2)) * 0.03 * amount;
  float rot = vnoise(t * 0.8, 3.3) * 0.03 * amount;
  float zoom = 1.0 + 0.07 * amount;
  vec2 d = (uv - 0.5) * vec2(srcRatio, 1.0);
  d = mat2(cos(rot), -sin(rot), sin(rot), cos(rot)) * d / zoom;
  vec2 u = d / vec2(srcRatio, 1.0) + 0.5 + off;
  return getColor(clamp(u, 0.0, 1.0));
}
