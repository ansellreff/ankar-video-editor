// Inward Wipe (approved in v3): B enters from both side edges and meets in the center. Sharp edge.
vec4 transition(vec2 uv) {
  float d = abs(uv.x - 0.5);
  return d > (1.0 - progress) * 0.5 ? getToColor(uv) : getFromColor(uv);
}
