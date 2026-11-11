// Dip to Black / White: A fades to a solid shade, then the shade fades into B.  param: shade (0 black, 1 white)
vec4 transition(vec2 uv) {
  vec4 solid = vec4(vec3(shade), 1.0);
  if (progress < 0.5) return mix(getFromColor(uv), solid, smoothstep(0.0, 1.0, progress * 2.0));
  return mix(solid, getToColor(uv), smoothstep(0.0, 1.0, progress * 2.0 - 1.0));
}
