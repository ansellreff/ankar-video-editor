// Sharpen (unsharp mask, 1.5 px). param: amount
vec4 effect(vec2 uv) {
  vec4 c = getColor(uv);
  vec2 o = px * 1.5;
  vec4 blur = (getColor(uv + vec2(o.x, 0.0)) + getColor(uv - vec2(o.x, 0.0)) +
               getColor(uv + vec2(0.0, o.y)) + getColor(uv - vec2(0.0, o.y))) * 0.25;
  return vec4(clamp(c.rgb + (c.rgb - blur.rgb) * amount * 1.5, 0.0, 1.0), c.a);
}
