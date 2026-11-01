import type { DroneState, Funnel, Heatmap, Message, Product, ReplayRow, SentinelEvent, Task } from './types';

export function parseReplay(source: string): ReplayRow[] {
  return source.split(/\r?\n/).filter(line => line.trim()).map((line, i) => {
    const row = JSON.parse(line) as ReplayRow;
    if (!Number.isFinite(row.t) || row.t < 0 || !row.msg || !['event', 'task', 'drone', 'heatmap'].includes(row.msg.kind)) throw new Error(`Invalid replay row ${i + 1}`);
    return row;
  }).sort((a, b) => a.t - b.t);
}

export class Store {
  events: SentinelEvent[] = [];
  tasks: Task[] = [];
  drone: DroneState | null = null;
  heatmap: Heatmap = { zones: {}, points: [] };
  funnels: Funnel[] = [];
  private seen = new Set<string>();
  reset() { this.events = []; this.tasks = []; this.drone = null; this.heatmap = { zones: {}, points: [] }; this.funnels = []; this.seen.clear(); }
  ingest(msg: Message) {
    if (msg.kind === 'event') {
      const e = msg.data;
      if (e.event_id && this.seen.has(e.event_id)) return;
      if (e.event_id) this.seen.add(e.event_id);
      this.events.unshift(e);
      if (this.events.length > 1000) { const dropped = this.events.pop(); if (dropped) this.seen.delete(dropped.event_id); }
      if (e.type === 'look') {
        const zone = this.heatmap.zones[e.zone_id] ?? { look_s: 0, looks: 0 };
        zone.look_s += Number(e.payload?.duration_s ?? 1.5); zone.looks++;
        this.heatmap.zones[e.zone_id] = zone;
        const hit = e.payload?.gaze_hit_xyz;
        if (Array.isArray(hit)) this.heatmap.points = [...this.heatmap.points.slice(-199), [...hit, 1]];
      }
    } else if (msg.kind === 'task') {
      this.tasks = [msg.data, ...this.tasks.filter(t => t.task_id !== msg.data.task_id)];
    } else if (msg.kind === 'drone') this.drone = msg.data;
    else this.heatmap = { zones: { ...msg.data.zones }, points: [...msg.data.points] };
  }
  funnel(products: Product[]): Funnel[] {
    if (this.funnels.length) return this.funnels;
    return products.map(p => {
      const events = this.events.filter(e => e.product_id === p.product_id);
      const count = (type: string) => events.filter(e => e.type === type).length;
      const looked = count('look'), picked_up = count('pick_up'), put_back = count('put_back'), kept = count('kept');
      return { ...p, passed_by: count('pass_by'), looked, interested: count('interest'), picked_up, put_back, kept, sold: 0, put_back_rate: picked_up ? put_back / picked_up : 0, flag_high_attention_low_conversion: looked >= 8 && kept / looked < .15 };
    }).sort((a, b) => b.looked - a.looked);
  }
}
