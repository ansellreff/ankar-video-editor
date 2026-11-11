// Cube Rotate: A and B are two faces of a cube turning to the left (pseudo-3D with perspective and shading).
vec4 transition(vec2 uv) {
  float p = progress * progress * (3.0 - 2.0 * progress);
  float th = p * 1.5708;
  float e = 1.0 - p;                                // shared edge position
  float persp = 0.22;
  if (uv.x < e) {
    float lu = uv.x / max(e, 1e-4);                 // 0 = far (left) edge of A
    float h = mix(1.0 - persp * sin(th), 1.0, lu);
    float v = (uv.y - 0.5) / h + 0.5;
    if (v < 0.0 || v > 1.0) return vec4(0.0, 0.0, 0.0, 1.0);
    return vec4(getFromColor(vec2(lu, v)).rgb * (1.0 - 0.5 * p), 1.0);
  }
  float lu = (uv.x - e) / max(p, 1e-4);             // 1 = far (right) edge of B
  float h = mix(1.0, 1.0 - persp * cos(th), lu);
  float v = (uv.y - 0.5) / h + 0.5;
  if (v < 0.0 || v > 1.0) return vec4(0.0, 0.0, 0.0, 1.0);
  return vec4(getToColor(vec2(lu, v)).rgb * (0.5 + 0.5 * p), 1.0);
}
