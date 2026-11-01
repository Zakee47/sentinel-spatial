import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import type { Site, Zone } from './types';
import type { Store } from './store';
import { decodePointCloud } from './layers';

const BLUE = 0x317cff;
const vec = (x: number, y: number, z: number) => new THREE.Vector3(x, z, -y);

export class TwinScene {
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(38, 1, .1, 100);
  private renderer: THREE.WebGLRenderer;
  private controls: OrbitControls;
  private fallback = new THREE.Group();
  private heat = new THREE.Group();
  private people = new THREE.Group();
  private drone = new THREE.Group();
  private depth = new THREE.Group();
  private labels: { el: HTMLElement; position: THREE.Vector3 }[] = [];
  private zoneHeat = new Map<string, THREE.Mesh>();
  private clock = new THREE.Clock();
  private lastPeople = 0;
  private showPeople = true;
  private labelLayer: HTMLElement;
  private store: Store;
  private host: HTMLElement;
  public source = 'Metric geometry';
  constructor(host: HTMLElement, site: Site, store: Store) {
    this.host = host; this.store = store;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.setClearColor(0xf0efed, 1);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    host.append(this.renderer.domElement);
    this.labelLayer = document.createElement('div'); this.labelLayer.className = 'scene-labels'; host.append(this.labelLayer);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true; this.controls.maxPolarAngle = Math.PI * .47; this.controls.minDistance = 6; this.controls.maxDistance = 35;
    this.resetView();
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0xb8b4ac, 2.5));
    const sun = new THREE.DirectionalLight(0xffffff, 3.2); sun.position.set(-5, 14, 8); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -15, right: 15, top: 15, bottom: -15 }); sun.shadow.bias = -.001;
    this.scene.add(sun);
    this.scene.add(this.fallback, this.heat, this.people, this.drone, this.depth);
    this.depth.visible = false;
    this.box(this.scene, vec(5, 4.6, -.15), [12, .22, 11], 0xe8e5e0);
    const grid = new THREE.GridHelper(12, 24, 0xd2cfc9, 0xdad7d1); grid.position.copy(vec(5, 4.6, -.025)); this.scene.add(grid);
    site.zones.forEach(z => this.makeZone(z));
    const fence = site.drone.geofence_polygon_xy;
    this.line([...fence, fence[0]].map(p => vec(p[0], p[1], .02)), BLUE, true, .34);
    const altitude = site.drone.patrol_altitude_m;
    const path = [site.drone.home_xy, ...site.zones.filter(z => z.kind === 'rack_bay').map(z => { const b = this.bounds(z); return [(b.x0 + b.x1) / 2, b.y0 - site.drone.patrol_standoff_m]; }), site.drone.home_xy];
    this.line(path.map(p => vec(p[0], p[1], altitude)), BLUE, true, .7);
    const home = new THREE.Mesh(new THREE.RingGeometry(.38, .42, 48), new THREE.MeshBasicMaterial({ color: BLUE, side: THREE.DoubleSide })); home.rotation.x = -Math.PI / 2; home.position.copy(vec(...[...site.drone.home_xy, .015] as [number, number, number])); this.scene.add(home);
    this.label('DRONE HOME', vec(5, 5, .12), 'subtle');
    for (const portal of site.portals) {
      const m = portal.T_twin_portal, p = vec(m[3], m[7], m[11]);
      const mark = new THREE.Mesh(new THREE.BoxGeometry(.25, .25, .04), new THREE.MeshStandardMaterial({ color: 0x191919 })); mark.position.copy(p); this.scene.add(mark);
      this.box(this.scene, p.clone().add(new THREE.Vector3(0, 0, .03)), [.13, .13, .02], 0xffffff);
      this.label(portal.id, p.clone().add(new THREE.Vector3(0, .3, 0)), 'portal-label');
    }
    const cam = vec(.5, .3, 3.2); this.box(this.scene, cam, [.32, .23, .45], 0x191919);
    for (const p of [[.5, 2, .1], [4.5, 2, .1], [4.5, 2.5, 1.8], [.5, 2.5, 1.8]]) this.line([cam, vec(...p as [number, number, number])], BLUE, false, .2);
    this.label('CAMERA–01', cam.clone().add(new THREE.Vector3(0, .4, 0)), 'camera-label');
    this.box(this.drone, new THREE.Vector3(), [.36, .1, .23], 0x191919);
    for (const x of [-.24, .24]) for (const z of [-.24, .24]) {
      const rotor = new THREE.Mesh(new THREE.TorusGeometry(.13, .018, 6, 20), new THREE.MeshStandardMaterial({ color: BLUE })); rotor.rotation.x = Math.PI / 2; rotor.position.set(x, 0, z); this.drone.add(rotor);
      this.line([new THREE.Vector3(), new THREE.Vector3(x, 0, z)], 0x191919, false, 1, this.drone);
    }
    this.drone.position.copy(vec(5, 5, altitude));
    new ResizeObserver(() => this.resize()).observe(host); this.resize();
    this.renderer.setAnimationLoop(() => this.draw());
    void this.loadTwin();
    void this.loadDepth();
  }
  private bounds(z: Zone) { return { x0: Math.min(...z.polygon_xy.map(p => p[0])), x1: Math.max(...z.polygon_xy.map(p => p[0])), y0: Math.min(...z.polygon_xy.map(p => p[1])), y1: Math.max(...z.polygon_xy.map(p => p[1])) }; }
  private box(parent: THREE.Object3D, position: THREE.Vector3, size: number[], color: number) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(size[0], size[1], size[2]), new THREE.MeshStandardMaterial({ color, roughness: .8 })); mesh.position.copy(position); mesh.castShadow = true; mesh.receiveShadow = true; parent.add(mesh); return mesh;
  }
  private line(points: THREE.Vector3[], color: number, dashed = false, opacity = 1, parent: THREE.Object3D = this.scene) {
    const material = dashed ? new THREE.LineDashedMaterial({ color, dashSize: .12, gapSize: .1, transparent: true, opacity }) : new THREE.LineBasicMaterial({ color, transparent: true, opacity });
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(points), material); line.computeLineDistances(); parent.add(line);
  }
  private makeZone(zone: Zone) {
    if (!['retail_shelf', 'rack_bay'].includes(zone.kind)) return;
    const b = this.bounds(zone), width = b.x1 - b.x0, depth = b.y1 - b.y0, height = zone.z_range[1], retail = zone.kind === 'retail_shelf', cx = (b.x0 + b.x1) / 2, cy = (b.y0 + b.y1) / 2;
    const levels = retail ? 4 : 3;
    for (const x of [b.x0 + .035, b.x1 - .035]) for (const y of [b.y0 + .04, b.y1 - .04]) this.box(this.fallback, vec(x, y, height / 2), [.055, height, .055], retail ? 0xbbb8b1 : 0x777e87);
    for (let level = 0; level < levels; level++) {
      const z = .12 + level * (height - .3) / levels;
      this.box(this.fallback, vec(cx, cy, z), [width, .06, depth], retail ? 0xfdfcf9 : 0xa8acaf);
      const n = retail ? 5 : 3;
      for (let item = 0; item < n; item++) {
        if (!retail && ((zone.id === 'bay-B-02' && level === 0) || (zone.id === 'bay-B-03' && item === 2 && level === 1))) continue;
        const h = retail ? .19 + (item % 3) * .05 : .52 + (item % 2) * .15;
        const x = b.x0 + width * (item + .5) / n;
        this.box(this.fallback, vec(x, cy, z + h / 2 + .04), [width / n * .76, h, depth * .7], retail ? [0xd9d5ca, 0xfaf9f5, 0x7d8998, 0xb7c6d9, 0xbbb5a3][item] : 0xb9a58a);
        if (!retail) this.box(this.fallback, vec(x, b.y0 + .17, z + h / 2), [.17, .11, .015], 0xf3f0e9);
      }
    }
    const overlay = new THREE.Mesh(new THREE.PlaneGeometry(width * .95, height * .88), new THREE.MeshBasicMaterial({ color: BLUE, transparent: true, opacity: .025, side: THREE.DoubleSide, depthWrite: false })); overlay.position.copy(vec(cx, b.y0 - .035, height / 2)); this.heat.add(overlay); this.zoneHeat.set(zone.id, overlay);
    if (!retail) this.label(zone.id.replace('bay-', '').replace('-', ' / '), vec(cx, cy, height + .35), 'bay-label');
    else if (zone.id.endsWith('2')) this.label('AISLE A · ATTENTION', vec(cx, b.y0, height + .65), 'attention-label');
  }
  private label(text: string, position: THREE.Vector3, cls: string) { const el = document.createElement('span'); el.className = `scene-label ${cls}`; el.textContent = text; this.labelLayer.append(el); this.labels.push({ el, position }); }
  resetView() { this.camera.position.set(15, 13.5, 12); this.controls?.target.copy(vec(4.3, 4.7, .5)); this.controls?.update(); }
  topView() { this.camera.position.copy(vec(5, 4.5, 22)); this.controls.target.copy(vec(5, 4.5, 0)); this.controls.update(); }
  toggleHeat(visible: boolean) { this.heat.visible = visible; }
  togglePeople(visible: boolean) { this.showPeople = visible; this.people.visible = visible; }
  toggleDepth(visible: boolean) { this.depth.visible = visible; }
  private cloud(buffer: ArrayBuffer, size: number) {
    const { positions, colors } = decodePointCloud(buffer);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    return new THREE.Points(geometry, new THREE.PointsMaterial({ size, vertexColors: true }));
  }
  private async loadDepth() {
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}depth/out/depth_points.bin`);
      if (!response.ok || response.headers.get('content-type')?.includes('text/html')) return;
      this.depth.add(this.cloud(await response.arrayBuffer(), .035));
      const toggle = document.querySelector<HTMLInputElement>('#depth-toggle');
      if (toggle) { toggle.disabled = false; toggle.parentElement!.title = 'Estimated depth · optional xyzrgb point cloud'; }
    } catch { /* Optional depth is unavailable; keep its toggle disabled. */ }
  }
  private resize() { const { clientWidth: w, clientHeight: h } = this.host; this.camera.aspect = w / Math.max(h, 1); this.camera.updateProjectionMatrix(); this.renderer.setSize(w, h); }
  private draw() {
    const t = this.clock.getElapsedTime(); this.controls.update();
    if (this.store.drone) { const d = this.store.drone; this.drone.position.lerp(vec(d.x, d.y, d.z), .12); this.drone.rotation.y = -d.yaw_deg * Math.PI / 180; }
    for (const [id, mesh] of this.zoneHeat) (mesh.material as THREE.MeshBasicMaterial).opacity = Math.min(.65, .03 + (this.store.heatmap.zones[id]?.look_s ?? 0) / 110);
    if (t - this.lastPeople > .3) { this.updatePeople(); this.lastPeople = t; }
    for (const label of this.labels) { const p = label.position.clone().project(this.camera); label.el.style.transform = `translate(-50%,-50%) translate(${(p.x + 1) / 2 * this.host.clientWidth}px,${(-p.y + 1) / 2 * this.host.clientHeight}px)`; label.el.style.display = p.z > 1 ? 'none' : ''; }
    this.renderer.render(this.scene, this.camera);
  }
  private updatePeople() {
    while (this.people.children.length) { const obj = this.people.children[0] as THREE.Mesh; obj.geometry?.dispose(); if (obj.material) (obj.material as THREE.Material).dispose(); this.people.remove(obj); }
    this.people.visible = this.showPeople;
    const latest = this.store.events[0]?.ts; if (!latest) return;
    const now = Date.parse(latest) + performance.now() - this.store.lastEventReceived, tracks = new Map<string, typeof this.store.events>();
    for (const e of this.store.events) { if (!e.track_id || e.x == null || e.y == null || now - Date.parse(e.ts) > 12_000) continue; const track = tracks.get(e.track_id) ?? []; if (track.length < 5) track.push(e); tracks.set(e.track_id, track); }
    for (const track of tracks.values()) {
      const e = track[0], age = Math.max(0, (now - Date.parse(e.ts)) / 12000), opacity = 1 - age;
      const dot = new THREE.Mesh(new THREE.CylinderGeometry(.08, .13, .32, 12), new THREE.MeshStandardMaterial({ color: BLUE, transparent: true, opacity })); dot.position.copy(vec(e.x!, e.y!, .19)); this.people.add(dot);
      if (track.length > 1) this.line(track.map(e => vec(e.x!, e.y!, .025)), BLUE, false, opacity * .4, this.people);
    }
    for (const p of this.store.heatmap.points.slice(-50)) { const dot = new THREE.Mesh(new THREE.SphereGeometry(.025, 6, 4), new THREE.MeshBasicMaterial({ color: BLUE })); dot.position.copy(vec(p[0], p[1] - .055, p[2])); this.people.add(dot); }
  }
  private async loadTwin() {
    const base = import.meta.env.BASE_URL;
    try {
      const res = await fetch(`${base}twin/out/twin.json`); if (!res.ok || !res.headers.get('content-type')?.includes('json')) return;
      const info = await res.json();
      if (info.source === 'colmap' && info.point_count > 0) {
        const binary = await fetch(`${base}twin/out/twin_points.bin`); if (!binary.ok) throw new Error('Point cloud missing');
        this.scene.add(this.cloud(await binary.arrayBuffer(), .025)); this.fallback.visible = false; this.source = 'COLMAP point cloud';
      } else {
        const gltf = await new GLTFLoader().loadAsync(`${base}twin/out/scene.glb`); gltf.scene.rotation.x = -Math.PI / 2; this.scene.add(gltf.scene); this.fallback.visible = false; this.source = info.source === 'simready' ? 'SimReady twin' : 'Metric box twin';
      }
      document.querySelector('#twin-source')!.textContent = this.source;
    } catch { /* Keep the metric fallback if optional twin assets are unavailable. */ }
  }
}
