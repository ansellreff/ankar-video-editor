// Barn Door Open: B opens outward from a vertical center line. Sharp edge.
vec4 transition(vec2 uv) {
  float d = abs(uv.x - 0.5);
  return d < progress * 0.5 ? getToColor(uv) : getFromColor(uv);
}
