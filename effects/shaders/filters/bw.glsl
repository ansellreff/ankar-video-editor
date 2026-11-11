// Black & White: luminance with a little extra contrast.
vec4 effect(vec2 uv) {
  vec4 src = getColor(uv);
  float l = luma(src.rgb);
  l = clamp((l - 0.5) * 1.12 + 0.5, 0.0, 1.0);
  return vec4(mix(src.rgb, vec3(l), amount), src.a);
}
