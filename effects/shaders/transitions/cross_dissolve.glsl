// Cross Dissolve: linear blend from A to B.
vec4 transition(vec2 uv) {
  return mix(getFromColor(uv), getToColor(uv), progress);
}
