// Zoom Pulse: a quick zoom punch on every beat. params: amount, bpm
vec4 effect(vec2 uv) {
  float beat = fract(time * max(bpm, 1.0) / 60.0);
  float s = 1.0 + amount * pow(1.0 - beat, 4.0);
  return getColor(0.5 + (uv - 0.5) / s);
}
