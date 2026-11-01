"""Hand calibration for footage without a QR portal.

4+ pixel <-> twin-point pairs give T_twin_cam via solvePnP; focal length is approximated (and, with
6+ pairs, searched over a range of horizontal FOVs for the lowest reprojection error).

Non-interactive:  python -m perception.calibrate_manual --image f.jpg --pairs perception/calib/camera-1.pairs.json
Interactive:      python -m perception.calibrate_manual --image f.jpg --twin-points "1,2,0;4,2,0;4,2,1.8;1,2,1.8"
                  (click each listed twin point in order; press any key when done)
pairs.json: [{"px": [u, v], "twin": [x, y, z]}, ...]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from perception.geometry import Camera, approx_intrinsics
from perception.pose import rt_to_T


def solve(px: np.ndarray, twin: np.ndarray, size: tuple[int, int], hfov_deg: float | None = None) -> tuple[Camera, float, float]:
    """Returns (camera, mean reprojection error px, hfov used)."""
    w, h = size
    fovs = [hfov_deg] if hfov_deg else (list(np.arange(35, 101, 1.0)) if len(px) >= 6 else [65.0])
    best: tuple[float, Camera, float] | None = None
    for fov in fovs:
        K = approx_intrinsics(w, h, fov)
        flag = cv2.SOLVEPNP_SQPNP if len(px) >= 4 else cv2.SOLVEPNP_P3P
        ok, rvec, tvec = cv2.solvePnP(twin.astype(np.float64), px.astype(np.float64), K, None, flags=flag)
        if not ok:
            continue
        rvec, tvec = cv2.solvePnPRefineLM(twin.astype(np.float64), px.astype(np.float64), K, None, rvec, tvec)
        proj, _ = cv2.projectPoints(twin.astype(np.float64), rvec, tvec, K, None)
        err = float(np.linalg.norm(proj.reshape(-1, 2) - px, axis=1).mean())
        T_cam_twin = rt_to_T(rvec, tvec)
        cam = Camera(K, np.linalg.inv(T_cam_twin), np.zeros(5), w, h)
        if best is None or err < best[0]:
            best = (err, cam, fov)
    if best is None:
        raise RuntimeError("calibration failed")
    return best[1], best[0], best[2]


def click_pairs(image: np.ndarray, twin_pts: list[list[float]]) -> list[dict]:
    clicks: list[tuple[int, int]] = []
    win = "calibrate: click " + " ".join(str(p) for p in twin_pts)

    def on_mouse(event: int, x: int, y: int, *_: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and len(clicks) < len(twin_pts):
            clicks.append((x, y))
            cv2.circle(image, (x, y), 5, (0, 0, 255), -1)
            cv2.putText(image, str(twin_pts[len(clicks) - 1]), (x + 6, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            cv2.imshow(win, image)

    cv2.imshow(win, image)
    cv2.setMouseCallback(win, on_mouse)
    while len(clicks) < len(twin_pts):
        if cv2.waitKey(50) == 27:
            break
    cv2.destroyAllWindows()
    return [{"px": list(c), "twin": t} for c, t in zip(clicks, twin_pts)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", required=True)
    ap.add_argument("--pairs", help="pairs json (written after clicking if --twin-points is given)")
    ap.add_argument("--twin-points", help='"x,y,z;x,y,z;..." to click interactively')
    ap.add_argument("--hfov", type=float, default=None)
    ap.add_argument("--camera", default="camera-1")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    img = cv2.imread(a.image)
    if img is None:
        raise SystemExit(f"cannot read {a.image}")
    h, w = img.shape[:2]
    if a.twin_points:
        pts = [[float(v) for v in p.split(",")] for p in a.twin_points.split(";")]
        pairs = click_pairs(img.copy(), pts)
        if a.pairs:
            Path(a.pairs).write_text(json.dumps(pairs, indent=1))
    else:
        pairs = json.loads(Path(a.pairs).read_text())
    if len(pairs) < 4:
        raise SystemExit("need 4+ pairs")
    px = np.array([p["px"] for p in pairs], float)
    tw = np.array([p["twin"] for p in pairs], float)
    cam, err, fov = solve(px, tw, (w, h), a.hfov)
    out = Path(a.out or Path(__file__).parent / "calib" / f"{a.camera}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    d = {"camera_id": a.camera, "method": "manual_pnp", "hfov_deg": fov, "reproj_error_px": round(err, 2), **cam.to_json(), "pairs": pairs}
    out.write_text(json.dumps(d, indent=1))
    print(f"wrote {out}  reprojection error {err:.2f}px  hfov {fov:.0f}deg  camera at {cam.center.round(2).tolist()}")
    vis = img.copy()
    proj, _ = cam.project(tw)
    for (u, v), (pu, pv) in zip(px, proj):
        cv2.circle(vis, (int(u), int(v)), 6, (0, 0, 255), 2)
        cv2.drawMarker(vis, (int(pu), int(pv)), (0, 255, 0), cv2.MARKER_CROSS, 12, 2)
    cv2.imwrite(str(out.with_suffix(".check.jpg")), vis)


if __name__ == "__main__":
    main()
