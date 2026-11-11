// Tilt-Shift: a sharp horizontal band, blur above and below (miniature look). params: focus (0..1 from top), width, blur (px)
vec4 effect(vec2 uv) {
  float y = 1.0 - uv.y;                                     // uv.y is bottom-up
  float k = smoothstep(width * 0.5, width * 0.5 + 0.25, abs(y - focus));
  vec4 c = getColor(uv);
  vec4 acc = c;
  float tot = 1.0;
  for (int i = 0; i < 16; i++) {
    float a = float(i) * 2.39996;
    float r = sqrt((float(i) + 0.5) / 16.0) * blur * k;
    acc += getColor(uv + vec2(cos(a), sin(a)) * px * r);
    tot += 1.0;
  }
  vec4 b = acc / tot;
  vec3 col = mix(vec3(luma(b.rgb)), b.rgb, 1.0 + 0.2 * k);
  return vec4(clamp(col, 0.0, 1.0), b.a);
}
