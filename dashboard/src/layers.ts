export function droneModeLabel(state: { mode?: string; driver?: string }): string {
  const mode = state.mode?.toLowerCase() ?? '';
  const driver = state.driver?.toLowerCase() ?? '';
  if (mode === 'piloted' || /livefeed|live_feed|piloted|human/.test(driver)) return 'PILOTED (human)';
  if (mode === 'sim' || /sim/.test(driver)) return 'SIM';
  return mode === 'live' ? 'LIVE' : 'MODE UNKNOWN';
}

export function decodePointCloud(buffer: ArrayBuffer) {
  if (!buffer.byteLength || buffer.byteLength % 24) throw new Error('Invalid xyzrgb cloud');
  const values = new Float32Array(buffer);
  const positions = new Float32Array(values.length / 2), colors = new Float32Array(values.length / 2);
  for (let i = 0; i < values.length / 6; i++) {
    const [x, y, z, r, g, b] = values.subarray(i * 6, i * 6 + 6);
    if (![x, y, z, r, g, b].every(Number.isFinite)) throw new Error('Non-finite cloud point');
    positions.set([x, z, -y], i * 3);
    colors.set([r, g, b].map(c => Math.max(0, Math.min(1, c > 1 ? c / 255 : c))), i * 3);
  }
  return { positions, colors };
}
