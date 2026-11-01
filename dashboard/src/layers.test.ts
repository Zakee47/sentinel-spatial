import { describe, expect, it } from 'vitest';
import { decodePointCloud, droneModeLabel } from './layers';

describe('optional spatial layers', () => {
  it('labels simulated and human-piloted drivers without treating live as autonomous', () => {
    expect(droneModeLabel({ mode: 'sim' })).toBe('SIM');
    expect(droneModeLabel({ driver: 'SimDriver' })).toBe('SIM');
    expect(droneModeLabel({ mode: 'piloted' })).toBe('PILOTED (human)');
    expect(droneModeLabel({ mode: 'live', driver: 'LiveFeedDriver' })).toBe('PILOTED (human)');
    expect(droneModeLabel({ mode: 'live' })).toBe('LIVE');
    expect(droneModeLabel({})).toBe('MODE UNKNOWN');
  });
  it('converts metric z-up xyzrgb points to three coordinates and normalized colors', () => {
    const result = decodePointCloud(new Float32Array([1, 2, 3, 255, 0, 128, 4, 5, 6, .5, 1, 0]).buffer);
    expect(Array.from(result.positions)).toEqual([1, 3, -2, 4, 6, -5]);
    expect(result.colors[0]).toBe(1);
    expect(result.colors[2]).toBeCloseTo(128 / 255);
    expect(result.colors[3]).toBe(.5);
  });
  it('rejects empty, malformed and non-finite clouds', () => {
    expect(() => decodePointCloud(new ArrayBuffer(0))).toThrow();
    expect(() => decodePointCloud(new ArrayBuffer(8))).toThrow();
    expect(() => decodePointCloud(new Float32Array([NaN, 0, 0, 1, 1, 1]).buffer)).toThrow();
  });
});
