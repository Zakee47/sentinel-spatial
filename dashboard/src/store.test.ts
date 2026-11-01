import { describe, expect, it } from 'vitest';
import { parseReplay, Store } from './store';
import type { Message, Product } from './types';
const product: Product = { product_id: 'SKU-007', name: 'Cocoa oat bar', brand: 'Test', price_gbp: 2, zone_id: 'shelf' };
const look = (id: string): Message => ({ kind: 'event', data: { event_id: id, ts: '2026-11-01T16:30:00Z', site_id: 'demo', zone_id: 'shelf', type: 'look', product_id: product.product_id, source: 'camera-1', payload: { duration_s: 2, gaze_hit_xyz: [1, 2, 1] } } });
describe('contract replay', () => {
  it('parses blank lines and sorts messages by time', () => { expect(parseReplay(`${JSON.stringify({t:2,msg:look('a')})}\n\n${JSON.stringify({t:0,msg:look('b')})}\n`).map(r=>r.t)).toEqual([0,2]); });
  it('rejects malformed rows', () => { expect(() => parseReplay('{"t":-1,"msg":{}}')).toThrow(); });
  it('deduplicates event IDs and aggregates dwell and gaze hits', () => { const s = new Store(); s.ingest(look('a')); s.ingest(look('a')); expect(s.events).toHaveLength(1); expect(s.heatmap.zones.shelf.look_s).toBe(2); expect(s.heatmap.points).toEqual([[1,2,1,1]]); });
  it('flags attention without conversion and can reset on seek', () => { const s = new Store(); for(let i=0;i<10;i++) s.ingest(look(String(i))); expect(s.funnel([product])[0].flag_high_attention_low_conversion).toBe(true); s.reset(); expect(s.events).toHaveLength(0); expect(s.funnel([product])[0].looked).toBe(0); });
  it('updates tasks instead of duplicating them', () => { const s = new Store(); const data = { task_id: 't', created_at: '', zone_id: 'bay', kind: 'restock', severity: 2, status: 'open', note: '' }; s.ingest({kind:'task',data}); s.ingest({kind:'task',data:{...data,status:'done'}}); expect(s.tasks).toHaveLength(1); expect(s.tasks[0].status).toBe('done'); });
});
