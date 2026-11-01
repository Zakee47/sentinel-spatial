import './style.css';
import { createIcons, ArrowUpRight, ArrowUp, Radio, Box, Crosshair, Layers, RotateCcw, Expand, Play, Pause, ShieldCheck, ScanLine, ChevronRight, Check, X, Bot, Square, Video, Battery, Eye, Package, Route, MessageSquare, CircleHelp } from 'lucide';
import { TwinScene } from './scene';
import { Store, parseReplay } from './store';
import { droneModeLabel } from './layers';
import type { AgentRun, DroneState, Funnel, Heatmap, Message, Product, ReplayRow, SentinelEvent, Site, Task } from './types';

const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
const icon = (name: string, cls = '') => `<i data-lucide="${name}" class="${cls}"></i>`;
const icons = () => createIcons({ icons: { ArrowUpRight, ArrowUp, Radio, Box, Crosshair, Layers, RotateCcw, Expand, Play, Pause, ShieldCheck, ScanLine, ChevronRight, Check, X, Bot, Square, Video, Battery, Eye, Package, Route, MessageSquare, CircleHelp } });
const params = new URLSearchParams(location.search);
const hostedReplay = location.hostname.endsWith('.github.io') && !params.has('api') && !params.has('live');
const replayUrl = params.get('replay') ?? (hostedReplay ? 'demo.jsonl' : null);
const base = import.meta.env.BASE_URL;
const api = (params.get('api') ?? import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '');
const store = new Store();
let products: Product[] = [], scene: TwinScene | undefined, connected = false, demo = false;
let rows: ReplayRow[] = [], cursor = 0, elapsed = 0, playing = true, speed = 1, duration = 60, reconnect: ReturnType<typeof setTimeout>;
let runs: AgentRun[] = [], reviews: SentinelEvent[] = [];
const reviewed = new Set<string>();
let lastTick = performance.now();

$('app').innerHTML = `
  <header class="topbar">
    <a class="brand" href="${base}" aria-label="Sentinel home"><img src="${base}favicon.svg" alt=""/><span>sentinel<span class="brand-period">.</span></span></a>
    <nav><a class="active" href="#overview">Overview</a><a href="#insights">Shelf intelligence</a><a href="#operations">Operations</a></nav>
    <div class="top-meta"><span class="mono">DEMO WAREHOUSE</span><span class="header-divider"></span><span class="connection" id="connection"><b></b>Connecting</span><button class="icon-button" id="help" aria-label="About Sentinel">${icon('circle-help')}</button></div>
  </header>
  <main id="overview">
    <section class="page-heading"><div><p class="eyebrow">SPATIAL INTELLIGENCE / 01</p><h1>Your floor. <span>In focus.</span></h1><p class="subtitle">Every shelf, every bay, every decision. One shared view.</p></div><div class="heading-actions"><span class="privacy">${icon('shield-check')} Anonymous by design</span><a class="button secondary" id="mode-link" href="?replay=demo.jsonl">${icon('play')} Open replay</a></div></section>
    <div id="notice" class="notice" role="status" hidden></div>
    <section class="workspace">
      <div class="twin-column">
        <section class="twin-card" aria-label="Interactive warehouse digital twin">
          <div class="panel-toolbar"><div class="panel-title">${icon('box')} Digital twin <span class="tiny-tag" id="twin-source">Box twin · unregistered</span></div><div class="view-controls"><button id="view-3d" class="selected">3D</button><button id="view-top">Top</button><button id="reset" class="icon-button" aria-label="Reset view">${icon('rotate-ccw')}</button><button id="fullscreen" class="icon-button" aria-label="Expand twin">${icon('expand')}</button></div></div>
          <div id="scene"><div class="scene-corner"><span class="live-dot"></span><span id="scene-status">LIVE SPATIAL VIEW</span><small>DEMO-WAREHOUSE / METRES</small></div><div class="scene-axis"><span>N</span><div>↑</div></div><div class="scene-legend"><label><input type="checkbox" id="heat-toggle" checked/> <span class="legend-square blue"></span> Shelf attention</label><label><input type="checkbox" id="people-toggle" checked/> <span class="legend-dot"></span> Anonymous tracks</label><label title="Show the box twin"><input type="radio" name="twin-layer" id="box-toggle" checked/> <span class="legend-square"></span> Box twin</label><label title="COLMAP cloud not available"><input type="radio" name="twin-layer" id="colmap-toggle" disabled/> <span class="legend-square"></span> COLMAP cloud</label><label title="Depth asset not available"><input type="checkbox" id="depth-toggle" disabled/> <span class="legend-square"></span> <span id="depth-name">Depth estimate</span></label><span class="legend-path"></span><span>Patrol route</span></div><div class="scene-hint">Drag to orbit · scroll to zoom</div></div>
          <div class="replay-bar" id="replay-bar" hidden><button id="play" class="icon-button" aria-label="Pause replay">${icon('pause')}</button><span class="mono" id="replay-time">00:00 / 01:00</span><input id="scrub" type="range" min="0" max="60" step="0.1" value="0" aria-label="Replay timeline"/><select id="speed" aria-label="Replay speed"><option value="0.5">0.5×</option><option selected value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select><button id="restart" class="icon-button" aria-label="Restart replay">${icon('rotate-ccw')}</button><span class="tiny-tag">READ ONLY</span></div>
          <div class="metrics"><div><span class="metric-label">SHELF ATTENTION</span><strong id="metric-attention">0<span>s</span></strong><small>Aggregate dwell time</small></div><div><span class="metric-label">LOOK → KEPT</span><strong id="metric-conversion">0<span>%</span></strong><small>Anonymous product funnel</small></div><div><span class="metric-label">BAYS INSPECTED</span><strong id="metric-bays">0<span>/ 4</span></strong><small>This patrol</small></div><div><span class="metric-label">OPEN TASKS</span><strong id="metric-tasks">0</strong><small>Ready for the floor</small></div></div>
        </section>
      </div>
      <aside class="right-column">
        <section class="drone-card panel" id="drone-panel"><div class="section-top"><p class="eyebrow">EYES IN THE AISLE</p><span class="tiny-tag" id="drone-mode">MODE UNKNOWN</span></div><h2>Drone–01 <span class="drone-state" id="drone-state">Standby</span></h2>
          <div class="drone-preview" id="drone-preview"><div class="preview-grid"></div><div class="drone-reticle">${icon('scan-line')}</div><span class="feed-label">DJI NEO 2 / <span id="feed-status">NO LIVE FEED</span></span><span class="feed-coordinate" id="drone-coordinates">X 5.0 / Y 5.0 / Z 0.0</span><img id="drone-feed" alt="Drone live feed" hidden/></div>
          <div class="drone-details"><span>${icon('battery')} <b id="battery">—</b></span><span>${icon('crosshair')} <b id="current-bay">Home</b></span></div><p id="last-decision" class="decision-note">Waiting for a bay inspection. Safety supervisor always has final say.</p>
          <div class="drone-actions"><button class="button" id="mission">${icon('bot')} Launch Devin mission ${icon('arrow-up-right')}</button><button class="stop-button" id="stop" title="Request safe landing">${icon('square')} STOP</button></div>
          <p class="safety-note">Geofence on · ≤ 1 m/s · ≤ 4 m · local flight loop</p><div id="agent-runs" class="agent-runs"></div>
        </section>
        <section class="assistant panel"><div class="assistant-heading"><span class="assistant-mark">${icon('message-square')}</span><div><h2>Ask Sentinel</h2><span>From observation to understanding.</span></div></div><p id="ask-answer" aria-live="polite">Your space has a story. Ask about a shelf, a product, or what needs attention.</p><button class="suggestion" id="ask-suggestion">Which shelf underperformed? ${icon('arrow-up-right')}</button><form id="ask-form"><label class="sr-only" for="ask-input">Ask about your floor</label><input id="ask-input" placeholder="Ask about your floor…" required/><button aria-label="Send question">${icon('arrow-up')}</button></form><span class="assistant-footnote">GROUNDED IN YOUR EVENT STORE</span></section>
      </aside>
    </section>
    <section class="cctv-card panel" id="cctv-card" hidden><div><p class="eyebrow">ON-SITE CAMERA / 01</p><h2>CCTV · camera-1</h2><p>Local MJPEG feed · video stays on site.</p></div><img id="cctv-feed" alt="Live CCTV from camera-1"/></section>
    <section class="rea-card panel" id="rea-card" hidden aria-label="Drone integration findings"></section>
    <section class="insight-grid" id="insights"><div class="panel funnel-panel"><div class="section-top"><div><p class="eyebrow">FROM ATTENTION TO ACTION</p><h2>What catches their eye.</h2></div><span class="tiny-tag">PRODUCT FUNNEL</span></div><div class="table-scroll"><table><thead><tr><th>Product / shelf</th><th>Looked</th><th>Interested</th><th>Picked</th><th>Put back</th><th>Kept</th><th>Sold*</th></tr></thead><tbody id="funnel-body"></tbody></table></div><div class="panel-footnote">${icon('eye')} High attention, low conversion is flagged automatically. <span>* Mock till data / unavailable in local replay</span></div></div>
    <div class="panel task-panel" id="operations"><div class="section-top"><div><p class="eyebrow">CLOSE THE LOOP</p><h2>Floor tasks <span id="task-count" class="count">0</span></h2></div>${icon('package')}</div><div id="tasks" class="task-list"></div></div></section>
    <section class="activity-grid"><div class="panel event-panel"><div class="section-top"><div><p class="eyebrow">OBSERVE → DECIDE</p><h2>The floor, as it happens.</h2></div><span id="event-count" class="tiny-tag">0 EVENTS</span></div><div id="events" class="event-list"></div></div><div class="panel review-panel"><div class="section-top"><div><p class="eyebrow">HUMAN IN THE LOOP</p><h2>Review queue <span class="count" id="review-count">0</span></h2></div>${icon('shield-check')}</div><div id="reviews"></div><p class="muted">Uncertain Decisions API answers stay here until a person confirms them.</p></div></section>
    <footer><span class="footer-brand">sentinel.</span><span>Video stays on site. Only event crops reach the Decisions API. No identities stored.</span><span class="built-with"><img src="${base}devin-mark.svg" alt="Devin"/> Mission planning by Devin</span></footer>
  </main><dialog id="mission-dialog"><form id="mission-form"><p class="eyebrow">MISSION LOOP / NOT FLIGHT CONTROL</p><h2>Give Devin a goal.</h2><p>The mission agent plans bay checks and raises tasks. The local safety supervisor validates every patrol.</p><label for="mission-goal">Mission goal</label><textarea id="mission-goal" required>End-of-shift stock check: inspect every rack bay, flag empty pick faces and misplaced cartons, and raise floor tasks.</textarea><div class="dialog-actions"><button type="button" class="button secondary" id="cancel-mission">Cancel</button><button class="button" type="submit">Launch mission ${icon('arrow-up-right')}</button></div></form></dialog>`;
icons();

function notice(message: string) { $('notice').textContent = message; $('notice').hidden = !message; }
function setStatus(label: string, live = false) { $('connection').innerHTML = `<b class="${live ? 'online' : ''}"></b>${esc(label)}`; }
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${api}${path}`, { method: body === undefined ? 'GET' : 'POST', headers: body === undefined ? {} : { 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(7000) });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json() as Promise<T>;
}
async function staticJson<T>(file: string): Promise<T> { const response = await fetch(`${base}${file}`); if (!response.ok) throw new Error(`Cannot load ${file}`); return response.json() as Promise<T>; }
function safeUrl(input: string | null): string | null { if (!input) return null; try { const u = new URL(input, location.href); return ['http:', 'https:'].includes(u.protocol) ? u.href : null; } catch { return null; } }
async function loadFindings() {
  try {
    const findings = await staticJson<{ verdict: string; verdict_summary: string; recommended_integration: string; video_paths: { name: string; how: string; live: boolean }[] }>('rea/findings.json');
    if (!findings.verdict || !Array.isArray(findings.video_paths)) return;
    $('rea-card').innerHTML = `<div><p class="eyebrow">REA · HOW THE APP FLIES THE DRONE</p><h2>Understand the link.<br/><span>Respect the limits.</span></h2><span class="tiny-tag">${esc(human(findings.verdict))}</span><p>${esc(findings.verdict_summary)}</p></div><div><h3>Video paths</h3>${findings.video_paths.map(path => `<details><summary>${esc(path.name)} <span>${path.live ? 'LIVE' : 'POST-FLIGHT'}</span></summary><p>${esc(path.how)}</p></details>`).join('')}</div><div><h3>Recommended integration</h3><p>${esc(findings.recommended_integration)}</p><a href="${base}rea/findings.json" target="_blank" rel="noopener noreferrer">View research findings ↗</a></div>`;
    $('rea-card').hidden = false;
  } catch { /* Findings arrive independently; omit the card until available. */ }
}
function connectCctv() {
  const image = $('cctv-feed') as HTMLImageElement;
  let timeout: ReturnType<typeof setTimeout>;
  let retry: ReturnType<typeof setTimeout>;
  const failed = () => {
    clearTimeout(timeout); clearTimeout(retry);
    $('cctv-card').hidden = true;
    image.removeAttribute('src');
    retry = setTimeout(connect, 30_000);
  };
  const connect = () => {
    image.onload = () => { clearTimeout(timeout); $('cctv-card').hidden = false; };
    image.onerror = failed;
    image.src = 'http://localhost:8090/cameras/camera-1/mjpeg';
    timeout = setTimeout(failed, 8000);
  };
  connect();
}
document.addEventListener('sentinel:open-camera', event => {
  const cameraId = (event as CustomEvent<{ cameraId: string }>).detail.cameraId;
  if (cameraId !== 'camera-1') return;
  const card = $('cctv-card'), image = $('cctv-feed') as HTMLImageElement;
  const show = () => { card.hidden = false; card.scrollIntoView({ behavior: 'smooth', block: 'center' }); };
  if (image.naturalWidth > 0) { show(); return; }
  image.addEventListener('load', show, { once: true });
  if (!image.getAttribute('src')) image.src = 'http://localhost:8090/cameras/camera-1/mjpeg';
});
function human(value: string) { return value.replaceAll('_', ' ').replaceAll('bay-', '').replace('aisle-A-shelf-', 'Shelf A'); }
function answerText(value: unknown) { return typeof value === 'string' ? value : JSON.stringify(value); }
function readOnly() { return !!replayUrl || demo || !connected; }
function render() {
  const funnels = store.funnel(products);
  const looks = funnels.reduce((n, f) => n + f.looked, 0), kept = funnels.reduce((n, f) => n + f.kept, 0);
  $('metric-attention').innerHTML = `${Math.round(Object.values(store.heatmap.zones).reduce((n, z) => n + z.look_s, 0))}<span>s</span>`;
  $('metric-conversion').innerHTML = `${looks ? Math.round(kept / looks * 100) : 0}<span>%</span>`;
  $('metric-bays').innerHTML = `${new Set(store.events.filter(e => e.type === 'bay_issue' || (e.type === 'patrol' && ['INSPECT', 'DECIDE'].includes(String(e.payload?.state)))).map(e => e.zone_id)).size}<span>/ 4</span>`;
  const tasks = store.tasks.filter(t => !['done', 'dismissed'].includes(t.status));
  $('metric-tasks').textContent = String(tasks.length); $('task-count').textContent = String(tasks.length);
  $('funnel-body').innerHTML = funnels.slice(0, 5).map(f => `<tr class="${f.flag_high_attention_low_conversion ? 'flagged' : ''}"><td><strong>${esc(f.name)}</strong><small>${esc(human(f.zone_id))}${f.flag_high_attention_low_conversion ? ' <span class="flag">HIGH ATTENTION, LOW CONVERSION</span>' : ''}</small></td>${[f.looked, f.interested, f.picked_up, f.put_back, f.kept, f.sold].map((n, i) => `<td class="${i === 0 ? 'attention-value' : ''}">${n}</td>`).join('')}</tr>`).join('');
  $('tasks').innerHTML = tasks.length ? tasks.slice(0, 5).map(t => `<article class="task-row"><span class="task-icon">${icon(t.kind === 'restock' ? 'package' : 'route')}</span><div><strong>${esc(human(t.kind))} · ${esc(human(t.zone_id))}</strong><p>${esc(t.note)}</p><small>${esc(t.status)} / severity ${Number(t.severity).toFixed(1)}</small></div>${icon('chevron-right')}</article>`).join('') : '<div class="empty-state">All clear for now.<small>Findings turn into spatially anchored tasks.</small></div>';
  $('events').innerHTML = store.events.slice(0, 7).map(e => `<article class="event-row"><span class="event-time">${esc(e.ts?.slice(11, 19))}</span><span class="event-marker ${e.type === 'bay_issue' ? 'issue' : ''}"></span><div><strong>${esc(human(e.type))}</strong><span> ${esc(human(e.zone_id))} · ${esc(e.source)}</span>${e.decision ? `<small>DECISIONS / ${esc(e.decision.question)} → ${esc(answerText(e.decision.answer))}</small>` : ''}</div><span class="confidence">${e.confidence == null ? '—' : `${Math.round(e.confidence * 100)}%`}</span></article>`).join('') || '<div class="empty-state">Listening for the next observation.</div>';
  $('event-count').textContent = `${store.events.length} EVENTS`;
  const queue = [...reviews, ...store.events.filter(e => e.decision?.policy === 'review')].filter((e, i, all) => !reviewed.has(e.event_id) && all.findIndex(a => a.event_id === e.event_id) === i);
  $('review-count').textContent = String(queue.length);
  $('reviews').innerHTML = queue.length ? queue.slice(0, 3).map(e => `<article class="review-row"><span class="tiny-tag">${Math.round((e.confidence ?? 0) * 100)}% CONFIDENCE</span><strong>${esc(human(e.type))} · ${esc(human(e.zone_id))}</strong><p>${esc(answerText(e.decision?.answer))}</p><div><button data-review="${esc(e.event_id)}" data-verdict="confirm" ${readOnly() ? 'disabled' : ''}>${icon('check')} Confirm</button><button data-review="${esc(e.event_id)}" data-verdict="reject" ${readOnly() ? 'disabled' : ''}>${icon('x')} Reject</button></div></article>`).join('') : '<div class="empty-state">No uncertain decisions.<small>Human judgement, where it matters.</small></div>';
  if (store.drone) renderDrone(store.drone);
  $('mission').toggleAttribute('disabled', readOnly()); $('stop').toggleAttribute('disabled', readOnly());
  $('agent-runs').innerHTML = runs.slice(0, 3).map(r => { const url = safeUrl(r.url); return url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${icon('bot')} ${esc(r.goal || r.session_id)} <span>${esc(r.status ?? 'running')}</span>${icon('arrow-up-right')}</a>` : ''; }).join('');
  icons();
}
function renderDrone(d: DroneState) {
  $('drone-state').textContent = human(d.state); $('drone-mode').textContent = droneModeLabel(d);
  $('battery').textContent = `${d.battery_pct.toFixed(0)}%`; $('current-bay').textContent = human(d.current_bay ?? 'Home');
  $('drone-coordinates').textContent = `X ${d.x.toFixed(1)} / Y ${d.y.toFixed(1)} / Z ${d.z.toFixed(1)} M`;
  $('last-decision').textContent = d.last_decision ? `Decisions API → ${answerText(d.last_decision)}` : 'Waiting for a bay inspection. Safety supervisor always has final say.';
  const feed = $('drone-feed') as HTMLImageElement, url = safeUrl(d.feed_url);
  if (url && feed.src !== url) feed.src = url; feed.hidden = !url; $('feed-status').textContent = url ? 'LIVE FEED' : 'NO LIVE FEED';
}
function handleMessage(msg: Message) { store.ingest(msg); render(); }
async function loadReplay(url: string, fallback = false) {
  const target = url.startsWith('http') || url.startsWith('/') ? url : `${base}${url}`;
  const response = await fetch(target); if (!response.ok) throw new Error(`Replay unavailable (${response.status})`);
  rows = parseReplay(await response.text()); duration = Math.max(1, rows.at(-1)?.t ?? 60); cursor = 0; elapsed = 0; store.reset();
  $('replay-bar').hidden = false; $('scrub').setAttribute('max', String(duration));
  $('scene-status').textContent = fallback ? 'LOCAL DEMO / SIMULATED' : 'RECORDED SPATIAL VIEW';
  setStatus(fallback ? 'Offline · local demo' : 'Replay · read only');
  $('mode-link').innerHTML = `${icon('radio')} ${replayUrl ? 'Connect live' : 'Open replay'}`;
  $('mode-link').setAttribute('href', replayUrl ? `${base}?live=1` : '?replay=demo.jsonl');
  drain(); render();
}
function drain() { while (cursor < rows.length && rows[cursor].t <= elapsed) store.ingest(rows[cursor++].msg); }
function seek(time: number) { elapsed = time; store.reset(); cursor = 0; drain(); render(); }
function clock(value: number) { return `${Math.floor(value / 60).toString().padStart(2, '0')}:${Math.floor(value % 60).toString().padStart(2, '0')}`; }
function tick(now: number) {
  if (rows.length) {
    if (playing) { const before = cursor; elapsed = Math.min(duration, elapsed + (now - lastTick) / 1000 * speed); drain(); if (before !== cursor) render(); if (elapsed >= duration) { playing = false; updatePlay(); } }
    ($('scrub') as HTMLInputElement).value = String(elapsed); $('replay-time').textContent = `${clock(elapsed)} / ${clock(duration)}`;
  }
  lastTick = now; requestAnimationFrame(tick);
}
function updatePlay() { $('play').innerHTML = icon(playing ? 'pause' : 'play'); $('play').setAttribute('aria-label', playing ? 'Pause replay' : 'Play replay'); icons(); }
function websocket() {
  const target = new URL(api || location.origin); target.protocol = target.protocol === 'https:' ? 'wss:' : 'ws:'; target.pathname = '/ws'; target.search = '';
  const socket = new WebSocket(target);
  socket.onopen = () => { connected = true; demo = false; rows = []; $('replay-bar').hidden = true; setStatus('Live · connected', true); notice(''); render(); };
  socket.onmessage = event => { try { handleMessage(JSON.parse(event.data) as Message); } catch { notice('An unreadable live message was ignored.'); } };
  socket.onclose = () => { connected = false; setStatus('Reconnecting'); render(); clearTimeout(reconnect); reconnect = setTimeout(websocket, 4000); };
}
async function boot() {
  void loadFindings();
  connectCctv();
  try {
    let site: Site;
    if (replayUrl) { [site, products] = await Promise.all([staticJson<Site>('site.json'), staticJson<Product[]>('products.json')]); }
    else {
      try { [site, products] = await Promise.all([request<Site>('/api/site'), request<Product[]>('/api/products')]); connected = true; }
      catch { [site, products] = await Promise.all([staticJson<Site>('site.json'), staticJson<Product[]>('products.json')]); demo = true; }
    }
    try { scene = new TwinScene($('scene'), site, store); } catch { notice('WebGL is unavailable. Event intelligence and controls still work.'); }
    if (replayUrl) await loadReplay(replayUrl);
    else if (demo) { notice('Backend not connected. Showing a labelled local simulation. Launch and STOP are disabled.'); await loadReplay('demo.jsonl', true); }
    else { await hydrate(); websocket(); setInterval(() => { if (connected) void refreshPanels(); }, 5000); }
    render(); requestAnimationFrame(tick);
  } catch (e) { notice(`Could not load Sentinel: ${(e as Error).message}. Check the replay URL or API connection.`); setStatus('Connection error'); }
}
async function hydrate() {
  await Promise.allSettled([
    request<SentinelEvent[]>('/api/events?limit=200').then(events => events.slice().reverse().forEach(data => store.ingest({ kind: 'event', data }))),
    request<Heatmap>('/api/heatmap').then(data => store.ingest({ kind: 'heatmap', data })),
    request<DroneState>('/api/drone/state').then(data => store.ingest({ kind: 'drone', data })),
    refreshPanels(),
  ]);
}
async function refreshPanels() {
  await Promise.allSettled([
    request<Funnel[]>('/api/funnel').then(data => { store.funnels = data; }),
    request<Task[]>('/api/tasks').then(data => { store.tasks = data; }),
    request<SentinelEvent[]>('/api/review').then(data => { reviews = data; }),
    request<AgentRun[]>('/api/agent/runs').then(data => { runs = data; }),
  ]); render();
}
$('view-3d').onclick = () => { scene?.resetView(); $('view-3d').classList.add('selected'); $('view-top').classList.remove('selected'); };
$('view-top').onclick = () => { scene?.topView(); $('view-top').classList.add('selected'); $('view-3d').classList.remove('selected'); };
$('reset').onclick = () => $('view-3d').click();
$('fullscreen').onclick = () => { if (document.fullscreenElement) void document.exitFullscreen(); else void document.querySelector('.twin-card')?.requestFullscreen(); };
$('heat-toggle').onchange = e => scene?.toggleHeat((e.target as HTMLInputElement).checked);
$('people-toggle').onchange = e => scene?.togglePeople((e.target as HTMLInputElement).checked);
$('box-toggle').onchange = e => { if ((e.target as HTMLInputElement).checked) scene?.toggleTwin('box'); };
$('colmap-toggle').onchange = e => { if ((e.target as HTMLInputElement).checked) scene?.toggleTwin('colmap'); };
$('depth-toggle').onchange = e => scene?.toggleDepth((e.target as HTMLInputElement).checked);
$('play').onclick = () => { if (elapsed >= duration) seek(0); playing = !playing; updatePlay(); };
$('restart').onclick = () => { seek(0); playing = true; updatePlay(); };
$('speed').onchange = e => { speed = Number((e.target as HTMLSelectElement).value); };
$('scrub').oninput = e => seek(Number((e.target as HTMLInputElement).value));
$('help').onclick = () => notice('Sentinel combines anonymous camera observations, a metric twin, Decisions API judgements, and a Devin mission planner. Stock footage, catalogue, till data and simulated positions are labelled. Video stays on site.');
$('mission').onclick = () => { if (!readOnly()) ($('mission-dialog') as HTMLDialogElement).showModal(); };
$('cancel-mission').onclick = () => ($('mission-dialog') as HTMLDialogElement).close();
$('mission-form').onsubmit = async e => { e.preventDefault(); const goal = ($('mission-goal') as HTMLTextAreaElement).value; if (readOnly()) return;
  const button = $('mission-form').querySelector('button[type="submit"]') as HTMLButtonElement; button.disabled = true;
  try { const result = await request<AgentRun>('/api/agent/run', { goal }); runs.unshift({ ...result, goal, status: 'running' }); ($('mission-dialog') as HTMLDialogElement).close(); notice('Devin mission launched. Patrols remain subject to the local safety supervisor.'); render(); }
  catch (e) { notice(`Mission not launched: ${(e as Error).message}`); } finally { button.disabled = false; }
};
$('stop').onclick = async () => { if (readOnly()) return; const button = $('stop') as HTMLButtonElement; button.disabled = true;
  try { await request('/api/drone/stop', {}); notice('STOP requested. Waiting for the local supervisor to acknowledge and land safely.'); }
  catch (e) { notice(`STOP request failed: ${(e as Error).message}. Use the physical flight controls.`); } finally { button.disabled = readOnly(); }
};
$('reviews').onclick = async e => { const button = (e.target as HTMLElement).closest<HTMLButtonElement>('button[data-review]'); if (!button || readOnly()) return; button.disabled = true;
  try { await request(`/api/review/${encodeURIComponent(button.dataset.review!)}`, { verdict: button.dataset.verdict }); reviewed.add(button.dataset.review!); render(); }
  catch (e) { notice(`Review was not saved: ${(e as Error).message}`); button.disabled = false; }
};
async function ask(question: string) {
  const button = $('ask-form').querySelector('button') as HTMLButtonElement; button.disabled = true; $('ask-answer').textContent = 'Looking at the event store…';
  try {
    if (readOnly()) { const f = store.funnel(products).find(f => f.flag_high_attention_low_conversion) ?? store.funnel(products)[0]; $('ask-answer').textContent = f?.looked ? `Local replay summary: ${f.name} on ${human(f.zone_id)} drew ${f.looked} looks, with ${f.kept} kept and ${f.put_back} put back. ${f.flag_high_attention_low_conversion ? 'High attention, low conversion — check placement, price and shelf availability.' : 'More observations are needed before flagging underperformance.'} ${store.tasks.filter(t => t.status === 'open').length} floor tasks are open. This is a deterministic replay summary, not an API answer.` : 'Local replay: let the timeline run to collect observations. Connect the live API to ask custom questions.'; }
    else { const result = await request<{ answer: string }>('/api/ask', { question }); $('ask-answer').textContent = result.answer; }
  } catch (e) { $('ask-answer').textContent = `Could not get an answer: ${(e as Error).message}`; } finally { button.disabled = false; }
}
$('ask-form').onsubmit = e => { e.preventDefault(); const input = $('ask-input') as HTMLInputElement; if (input.value.trim()) void ask(input.value.trim()); };
$('ask-suggestion').onclick = () => { ($('ask-input') as HTMLInputElement).value = 'Which shelf underperformed?'; void ask('Which shelf underperformed?'); };
void boot();
