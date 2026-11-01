"""Camera perception runner.

python -m perception.run --source perception/footage/aisle.mp4 --camera camera-1 [--show] [--mock]
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import time
import uuid
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from perception.emit import EventSink
from perception.gaze import (
    LookTracker,
    PassByTracker,
    cast_gaze,
    head_direction_twin,
    head_position,
    head_yaw_from_keypoints,
)
from perception.geometry import Camera, approx_intrinsics, floor_position
from perception.pose import detect_portals
from perception.reach import ReachCallbacks, ReachMachine
from perception.site import Site, Zone, load_site

HERE = Path(__file__).resolve().parent
CROPS = HERE.parent / "crops"
L_WRIST, R_WRIST, L_SH, R_SH, L_HIP, R_HIP, L_ANK, R_ANK = 9, 10, 5, 6, 11, 12, 15, 16
HEAD = [0, 1, 2, 3, 4]


def load_camera(site: Site, camera_id: str, first_frame: np.ndarray, calib: str | None) -> tuple[Camera, str]:
    h, w = first_frame.shape[:2]
    path = Path(calib) if calib else HERE / "calib" / f"{camera_id}.json"
    if path.exists():
        cam = Camera.load(path)
        if cam.width and (cam.width, cam.height) != (w, h):  # rescale intrinsics if video differs
            sx, sy = w / cam.width, h / cam.height
            cam.K = cam.K.copy()
            cam.K[0] *= sx
            cam.K[1] *= sy
            cam.width, cam.height = w, h
        return cam, f"calib:{path.name}"
    K = approx_intrinsics(w, h)
    cfg = site.camera(camera_id)
    poses = detect_portals(first_frame, site, K, None, cfg.get("anchor_portal"))
    if poses:
        best = min(poses, key=lambda p: p.reproj_error_px)
        return Camera(K, best.T_twin_cam, np.zeros(5), w, h), f"portal:{best.portal_id} err={best.reproj_error_px:.2f}px"
    if cfg.get("T_twin_cam_override"):
        return Camera(K, np.array(cfg["T_twin_cam_override"], float).reshape(4, 4), np.zeros(5), w, h), "site_override"
    raise SystemExit(f"no calibration for {camera_id}: run perception.calibrate_manual or show a QR portal")


def zone_hull(cam: Camera, z: Zone) -> np.ndarray | None:
    px, depth = cam.project(z.corners())
    if np.any(depth <= 0.05):
        return None
    return cv2.convexHull(px.astype(np.float32)).reshape(-1, 2)


def jpeg(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else b""


def crop_rect(img: np.ndarray, x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    h, w = img.shape[:2]
    x0, y0, x1, y1 = int(max(0, x0)), int(max(0, y0)), int(min(w, x1)), int(min(h, y1))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return np.zeros((8, 8, 3), np.uint8)
    return img[y0:y1, x0:x1].copy()


def blur_faces(img: np.ndarray, kps: np.ndarray) -> np.ndarray:
    out = img.copy()
    for kp in kps:
        pts = kp[HEAD][kp[HEAD, 2] > 0.3, :2]
        if len(pts) < 2:
            continue
        c = pts.mean(axis=0)
        r = max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1]), 10) * 1.3
        x0, y0, x1, y1 = int(c[0] - r), int(c[1] - r), int(c[0] + r), int(c[1] + r)
        roi = crop_rect(out, x0, y0, x1, y1)
        if roi.shape[0] > 8:
            out[max(0, y0):max(0, y0) + roi.shape[0], max(0, x0):max(0, x0) + roi.shape[1]] = cv2.GaussianBlur(roi, (0, 0), 12)
    return out


def dist_to_zone_xy(xy: np.ndarray, z: Zone) -> float:
    lo, hi = z.box_min[:2], z.box_max[:2]
    d = np.maximum(np.maximum(lo - xy, 0), xy - hi)
    return float(np.linalg.norm(d))


def draw_minimap(img: np.ndarray, site: Site, cam: Camera, people: list[dict], looked: set[str]) -> None:
    W, H, s = 260, 170, 50.0  # px, px per metre; shows x in [-0.2, 5], y in [-0.6, 2.8]
    ox, oy = img.shape[1] - W - 10, 10
    over = img.copy()
    cv2.rectangle(over, (ox, oy), (ox + W, oy + H), (20, 20, 20), -1)
    cv2.addWeighted(over, 0.75, img, 0.25, 0, img)

    def m(x: float, y: float) -> tuple[int, int]:
        return int(ox + (x + 0.2) * s), int(oy + H - (y + 0.6) * s)

    for z in site.zones:
        if z.kind not in ("retail_shelf", "aisle_floor"):
            continue
        pts = np.array([m(*p) for p in z.polygon_xy], np.int32)
        col = (0, 200, 255) if z.id in looked else ((90, 90, 90) if z.kind == "aisle_floor" else (200, 160, 60))
        cv2.polylines(img, [pts], True, col, 2 if z.kind == "retail_shelf" else 1)
    cx, cy = cam.center[:2]
    cv2.drawMarker(img, m(cx, cy), (255, 255, 255), cv2.MARKER_TRIANGLE_UP, 10, 2)
    for p in people:
        if p.get("xy") is None:
            continue
        cv2.circle(img, m(*p["xy"]), 5, p["color"], -1)
        if p.get("hit") is not None:
            cv2.line(img, m(*p["xy"]), m(*p["hit"][:2]), (0, 200, 255), 1)
        elif p.get("gaze") is not None:
            e = p["xy"] + p["gaze"][:2] * 1.0
            cv2.line(img, m(*p["xy"]), m(*e), (180, 180, 180), 1)
    cv2.putText(img, "twin (top-down)", (ox + 6, oy + 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (220, 220, 220), 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="perception/footage/aisle.mp4")
    ap.add_argument("--camera", default="camera-1")
    ap.add_argument("--calib", default=None)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--mock", action="store_true", help="SENTINEL_DECISIONS_MOCK=1")
    ap.add_argument("--no-post", action="store_true")
    ap.add_argument("--weights", default="yolo26n-pose.pt")
    ap.add_argument("--fps", type=float, default=None, help="process at this fps (default site camera fps)")
    ap.add_argument("--max-seconds", type=float, default=None)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--out-dir", default=str(HERE / "out"))
    a = ap.parse_args()
    if a.mock:
        os.environ["SENTINEL_DECISIONS_MOCK"] = "1"
    import sentinel_decisions as sd  # after env is set
    from ultralytics import YOLO

    site = load_site()
    th = site.thresholds
    src: int | str = int(a.source) if a.source.isdigit() else a.source
    capture = cv2.VideoCapture(src)
    ok, frame = capture.read()
    if not ok:
        raise SystemExit(f"cannot read {a.source} (run perception/fetch_footage.sh)")
    cam, how = load_camera(site, a.camera, frame, a.calib)
    print(f"[camera] {a.camera} pose from {how}; centre {cam.center.round(2).tolist()}")
    vid_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    proc_fps = a.fps or float(site.camera(a.camera).get("fps", 15))
    stride = max(1, round(vid_fps / proc_fps))

    try:
        model = YOLO(a.weights)
    except Exception as e:  # noqa: BLE001
        print(f"[model] {a.weights} unavailable ({e}); falling back to yolo11n-pose.pt")
        model = YOLO("yolo11n-pose.pt")

    shelves = site.zones_of("retail_shelf")
    aisle = site.zones_of("aisle_floor")[0]
    hulls = {z.id: zone_hull(cam, z) for z in shelves}
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    CROPS.mkdir(exist_ok=True)
    sink = EventSink(out_dir / "events.jsonl", post=not a.no_post)
    looks = LookTracker(th["look_min_s"], th["interest_min_s"])
    passby = PassByTracker(aisle)
    buf: deque[np.ndarray] = deque(maxlen=max(2, int(proc_fps * 0.6)))
    state: dict = {"frame": frame, "kps": np.zeros((0, 17, 3)), "hands": {}}

    def save(img: np.ndarray, tag: str) -> bytes:
        b = jpeg(img)
        (CROPS / f"{tag}-{uuid.uuid4().hex[:8]}.jpg").write_bytes(b)
        return b

    def shelf_crop_of(img: np.ndarray, zid: str) -> np.ndarray:
        hl = hulls.get(zid)
        if hl is None:
            return img
        x0, y0 = hl.min(axis=0)
        x1, y1 = hl.max(axis=0)
        return crop_rect(blur_faces(img, state["kps"]), x0, y0, x1, y1)

    def logged(fn):  # type: ignore[no-untyped-def]
        def inner(*args):  # type: ignore[no-untyped-def]
            d = fn(*args)
            print(f"[decision] {d.question} -> {d.value} conf={d.confidence} policy={d.policy} {d.latency_s:.2f}s", flush=True)
            return d
        return inner

    hold_th = float(th["holding_product"]["review"])
    reach = ReachMachine(ReachCallbacks(
        shelf_crop=lambda zid: save(shelf_crop_of(state["frame"], zid), "after"),
        before_crop=lambda zid: save(shelf_crop_of(buf[0] if buf else state["frame"], zid), "before"),
        hand_crop=lambda tid: save(state["hands"].get(tid, np.zeros((8, 8, 3), np.uint8)), "hand"),
        holding_product=logged(sd.holding_product),
        reach_outcome=logged(sd.reach_outcome),
        holding_threshold=hold_th,
    ))

    h, w = frame.shape[:2]
    tmp_video = out_dir / "annotated_raw.mp4"
    writer = cv2.VideoWriter(str(tmp_video), cv2.VideoWriter_fourcc(*"mp4v"), proc_fps, (w, h))
    colors: dict[str, tuple[int, int, int]] = {}
    active: set[str] = set()
    looked_flash: dict[str, float] = {}
    fidx, t0 = 0, time.time()

    def finish(evs: list[dict], xyz: np.ndarray | None = None) -> None:
        for ev in evs:
            ev.update({"site_id": site.site_id, "source": a.camera})
            ev["track_id"] = f"t{ev['track_id']}" if ev.get("track_id") and not str(ev["track_id"]).startswith("t") else ev.get("track_id")
            if ev.get("product_id") is None and ev["type"] in ("look", "interest"):
                ev["product_id"] = None
            if xyz is not None and "x" not in ev:
                ev.update({"x": round(float(xyz[0]), 3), "y": round(float(xyz[1]), 3), "z": 0.0})
            sink.emit(ev)

    while ok:
        if fidx % stride == 0:
            t = fidx / vid_fps
            if a.max_seconds and t > a.max_seconds:
                break
            state["frame"] = frame
            res = model.track(frame, persist=True, verbose=False, imgsz=a.imgsz, classes=[0])[0]
            vis = res.plot(boxes=True, labels=True, conf=False, line_width=2)
            kps = res.keypoints.data.cpu().numpy() if res.keypoints is not None else np.zeros((0, 17, 3))
            state["kps"] = kps
            ids = res.boxes.id.int().cpu().tolist() if res.boxes is not None and res.boxes.id is not None else []
            boxes = res.boxes.xyxy.cpu().numpy() if res.boxes is not None else np.zeros((0, 4))
            people, seen = [], set()
            for tid_i, kp, box in zip(ids, kps, boxes):
                tid = str(tid_i)
                seen.add(tid)
                colors.setdefault(tid, tuple(int(c) for c in np.random.default_rng(tid_i).integers(80, 255, 3)))
                fp, method = floor_position(cam, [tuple(kp[L_ANK]), tuple(kp[R_ANK])], site.floor_plane,
                                            fallback_px=((box[0] + box[2]) / 2, box[3]),
                                            hips=[tuple(kp[L_HIP]), tuple(kp[R_HIP])])
                xy = fp[:2] if fp is not None else None
                p = {"tid": tid, "xy": xy, "color": colors[tid], "gaze": None, "hit": None}
                finish(passby.update(tid, xy), fp)
                # head direction + gaze cone
                hy = head_yaw_from_keypoints(kp)
                head_kp = kp[HEAD][kp[HEAD, 2] > 0.3, :2]
                if xy is not None and hy is not None and len(head_kp):
                    head = head_position(cam, tuple(head_kp.mean(axis=0)), xy)
                    g = head_direction_twin(cam, head, hy[0], hy[1])
                    hit = cast_gaze(head, g, shelves, th["gaze_half_angle_deg"])
                    p["gaze"] = g
                    end = hit.hit_xyz if hit.hit_xyz is not None else head + g * 1.5
                    (hu, hv), (eu, ev_) = cam.project(np.array([head, end]))[0]
                    cv2.arrowedLine(vis, (int(hu), int(hv)), (int(eu), int(ev_)), (0, 200, 255) if hit.zone_id else (200, 200, 200), 2, tipLength=0.08)
                    if hit.zone_id:
                        p["hit"] = hit.hit_xyz
                        looked_flash[hit.zone_id] = t
                    finish(looks.update(tid, t, hit.zone_id, hit.hit_xyz), fp)
                else:
                    finish(looks.update(tid, t, None), fp)
                # reach
                wrist_zone, prod = None, None
                near = False
                if xy is not None:
                    torso = np.linalg.norm(kp[[L_SH, R_SH], :2].mean(0) - kp[[L_HIP, R_HIP], :2].mean(0))
                    for wi, si in ((L_WRIST, L_SH), (R_WRIST, R_SH)):
                        if kp[wi, 2] < 0.4:
                            continue
                        extended = np.linalg.norm(kp[wi, :2] - kp[si, :2]) > 0.55 * max(torso, 1)
                        above_hip = kp[wi, 1] < kp[[L_HIP, R_HIP], 1].mean() + 0.1 * torso
                        for z in shelves:
                            hl = hulls[z.id]
                            if hl is None or dist_to_zone_xy(xy, z) > 1.0:
                                continue
                            near = True
                            if extended and above_hip and cv2.pointPolygonTest(hl.astype(np.float32), (float(kp[wi, 0]), float(kp[wi, 1])), False) >= 0:
                                wrist_zone = z.id
                                o, d = cam.pixel_ray(float(kp[wi, 0]), float(kp[wi, 1]))
                                ty = (z.box_min[1] - o[1]) / d[1] if abs(d[1]) > 1e-6 else 0
                                prod = z.product_at_x(float(o[0] + ty * d[0]))
                                r = max(torso * 0.35, 24)
                                state["hands"][tid] = crop_rect(blur_faces(frame, kps), kp[wi, 0] - r, kp[wi, 1] - r, kp[wi, 0] + r, kp[wi, 1] + r)
                                cv2.circle(vis, (int(kp[wi, 0]), int(kp[wi, 1])), 14, (0, 0, 255), 3)
                                break
                        if wrist_zone:
                            break
                finish(reach.update(tid, t, wrist_zone, prod, near), fp)
                if fp is not None:
                    (fu, fv), = cam.project(fp[None])[0]
                    fu, fv = float(np.clip(fu, 10, w - 10)), float(np.clip(fv, 10, h - 12))  # off-screen feet: clamp
                    cv2.circle(vis, (int(fu), int(fv)), 7, colors[tid], -1)
                    cv2.circle(vis, (int(fu), int(fv)), 9, (0, 0, 0), 2)
                    cv2.putText(vis, f"t{tid} floor ({xy[0]:.2f},{xy[1]:.2f}) via {method}", (int(min(fu + 10, w - 330)), int(fv) - 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
                rs = reach.tracks.get(tid)
                if rs and rs.state != "IDLE":
                    cv2.putText(vis, rs.state, (int(box[0]), int(box[1]) - 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
                people.append(p)
            for tid in active - seen:
                finish(reach.lost(tid))
            active = seen
            finish(looks.expire(t))
            looked = {z for z, lt in looked_flash.items() if t - lt < 0.3}
            for zid, hl in hulls.items():
                if hl is None:
                    continue
                col = (0, 200, 255) if zid in looked else (200, 160, 60)
                if zid in looked:
                    over = vis.copy()
                    cv2.fillPoly(over, [hl.astype(np.int32)], col)
                    cv2.addWeighted(over, 0.25, vis, 0.75, 0, vis)
                cv2.polylines(vis, [hl.astype(np.int32)], True, col, 2)
                c = hl.mean(axis=0)
                cv2.putText(vis, zid.replace("aisle-A-", ""), (int(np.clip(c[0], 10, w - 80)) - 30, int(np.clip(c[1], 40, h - 10))), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2)
            draw_minimap(vis, site, cam, people, looked)
            cv2.putText(vis, f"{a.camera}  t={t:5.1f}s  events={sink.count}", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            writer.write(vis)
            buf.append(frame.copy())
            if a.show:
                cv2.imshow("sentinel perception", vis)
                if cv2.waitKey(1) == 27:
                    break
        ok, frame = capture.read()
        fidx += 1

    finish(looks.flush())
    finish(reach.flush())
    writer.release()
    sink.close()
    final = out_dir / "annotated.mp4"
    if shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp_video), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(final)], check=False)
        tmp_video.unlink(missing_ok=True)
    else:
        tmp_video.rename(final)
    print(f"[done] {fidx} frames in {time.time() - t0:.1f}s, {sink.count} events -> {sink.out_path}; video -> {final}"
          f"; server {'ok' if sink.server_ok else 'down (jsonl only)'}")


if __name__ == "__main__":
    main()
