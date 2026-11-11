// Pixelize: A breaks into big pixels, they swap to B and sharpen again.
vec4 transition(vec2 uv) {
  float k = sin(progress * 3.14159);
  float cells = mix(400.0, 12.0, k * k);
  vec2 g = vec2(cells * ratio, cells);
  vec2 u = k > 0.02 ? (floor(uv * g) + 0.5) / g : uv;
  return progress < 0.5 ? getFromColor(u) : getToColor(u);
}
