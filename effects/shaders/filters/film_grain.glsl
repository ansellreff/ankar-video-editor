// Film Grain: animated luminance noise, strongest in the mid-tones. params: amount, size (px)
vec4 effect(vec2 uv) {
  vec4 c = getColor(uv);
  vec2 cell = floor(uv / (px * size));
  float n = rand(cell + vec2(floor(time * 24.0) * 7.31, 0.0)) - 0.5;
  float l = luma(c.rgb);
  float mid = 1.0 - abs(l - 0.5) * 1.4;
  return vec4(clamp(c.rgb + n * amount * mid, 0.0, 1.0), c.a);
}
