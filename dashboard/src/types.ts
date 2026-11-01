export interface Zone { id: string; kind: string; polygon_xy: number[][]; z_range: number[]; products?: string[] }
export interface Site { site_id: string; zones: Zone[]; portals: { id: string; size_m: number; T_twin_portal: number[] }[]; cameras: { id: string; kind: string; anchor_portal?: string }[]; drone: { home_xy: number[]; geofence_polygon_xy: number[][]; patrol_altitude_m: number; patrol_standoff_m: number; max_alt_m: number; max_speed_mps: number; min_battery_pct: number } }
export interface Product { product_id: string; name: string; brand: string; price_gbp: number; zone_id: string }
export interface SentinelEvent { event_id: string; ts: string; site_id: string; zone_id: string; type: string; product_id?: string; x?: number; y?: number; z?: number; source: string; track_id?: string; confidence?: number; decision?: { question: string; answer: unknown; policy: string }; payload: Record<string, unknown> }
export interface Task { task_id: string; created_at: string; zone_id: string; kind: string; severity: number; status: string; note: string }
export interface DroneState { ts: string; mode: 'sim' | 'live'; state: string; x: number; y: number; z: number; yaw_deg: number; battery_pct: number; current_bay: string | null; last_decision: Record<string, unknown> | null; stop_requested: boolean; feed_url: string | null }
export interface Heatmap { zones: Record<string, { look_s: number; looks: number }>; points: number[][] }
export interface Funnel { product_id: string; name: string; zone_id: string; passed_by: number; looked: number; interested: number; picked_up: number; put_back: number; kept: number; sold: number; put_back_rate: number; flag_high_attention_low_conversion: boolean }
export type Message = { kind: 'event'; data: SentinelEvent } | { kind: 'task'; data: Task } | { kind: 'drone'; data: DroneState } | { kind: 'heatmap'; data: Heatmap };
export interface ReplayRow { t: number; msg: Message }
export interface AgentRun { session_id: string; url: string; goal: string; status?: string; created_at?: string }
