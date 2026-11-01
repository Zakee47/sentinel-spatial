"""CPU monocular depth -> pseudo-LiDAR, optionally fused using COLMAP poses."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from depth.cloud import Array, back_project, export_cloud, transform_points
from depth.colmap import Camera, Pose, find_model, read_model, sparse_depth_scale

METRIC_MODEL = "depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf"
RELATIVE_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"


class DepthEstimator:
    def __init__(
        self,
        relative_scale_m: float = 5.0,
        model: str = METRIC_MODEL,
        force_relative: bool = False,
    ) -> None:
        import torch
        from transformers import pipeline

        torch.set_num_threads(min(torch.get_num_threads(), 4))
        self.relative = force_relative
        self.relative_scale_m = relative_scale_m
        self.model = RELATIVE_MODEL if force_relative else model
        try:
            self.pipe = pipeline("depth-estimation", model=self.model, device=-1)
        except (OSError, ValueError, RuntimeError) as exc:
            if force_relative:
                raise
            print(
                f"Metric model unavailable ({exc}); trying explicitly labelled relative fallback",
                file=sys.stderr,
            )
            self.relative = True
            self.model = RELATIVE_MODEL
            self.pipe = pipeline("depth-estimation", model=self.model, device=-1)

    def predict(self, rgb: Any) -> Array:
        result = self.pipe(Image.fromarray(rgb))
        # 'depth' is an 8-bit visualisation: only predicted_depth preserves metric values.
        raw = result["predicted_depth"].detach().cpu().numpy().squeeze().astype(float)
        raw = cv2.resize(
            raw, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_CUBIC
        )
        if self.relative:
            # Relative model predicts inverse-depth-like values, not metres.
            raw = np.maximum(raw, max(float(np.nanpercentile(raw, 1)), 1e-6))
            raw = 1.0 / raw
            raw *= self.relative_scale_m / float(np.nanmedian(raw))
        return raw


def approximate_intrinsics(width: int, height: int, hfov_deg: float = 90.0) -> Array:
    """Uncalibrated pinhole approximation, not a claimed DJI factory calibration."""
    if not 1 < hfov_deg < 179:
        raise ValueError("Horizontal field of view must be between 1 and 179 degrees")
    focal = width / (2 * np.tan(np.deg2rad(hfov_deg) / 2))
    return np.array(
        [[focal, 0, (width - 1) / 2], [0, focal, (height - 1) / 2], [0, 0, 1]]
    )


def _resize(rgb: Any, max_width: int) -> Any:
    if rgb.shape[1] <= max_width:
        return rgb
    return cv2.resize(rgb, (max_width, round(rgb.shape[0] * max_width / rgb.shape[1])))


def video_frames(
    path: Path, every_s: float, max_frames: int, max_width: int, frames_dir: Path
) -> list[tuple[str, Any, float]]:
    if path.is_dir():
        paths = sorted(
            p for p in path.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
        return [
            (
                p.name,
                _resize(np.asarray(Image.open(p).convert("RGB")), max_width),
                float(i),
            )
            for i, p in enumerate(paths[:max_frames])
        ]
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open video {path}")
    frames = []
    frames_dir.mkdir(parents=True, exist_ok=True)
    try:
        for index in range(max_frames):
            timestamp = index * every_s
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, bgr = cap.read()
            if not ok:
                break
            rgb = _resize(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), max_width)
            name = f"frame_{index:06d}.jpg"
            Image.fromarray(rgb).save(frames_dir / name)
            frames.append((name, rgb, timestamp))
    finally:
        cap.release()
    if not frames:
        raise ValueError("No decodable frames")
    return frames


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "video", type=Path, help="Video, or image directory matching COLMAP names"
    )
    parser.add_argument("--out", type=Path, default=Path("depth/out"))
    parser.add_argument("--work", type=Path, default=Path("depth/work"))
    parser.add_argument("--every-s", type=float, default=2)
    parser.add_argument("--max-frames", type=int, default=3)
    parser.add_argument("--max-width", type=int, default=640)
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--voxel-m", type=float, default=0.05)
    parser.add_argument("--hfov-deg", type=float, default=90)
    parser.add_argument("--max-depth-m", type=float, default=30)
    parser.add_argument("--camera-height-m", type=float, default=1.5)
    parser.add_argument(
        "--intrinsics", type=Path, help="JSON: width,height,fx,fy,cx,cy"
    )
    parser.add_argument(
        "--colmap",
        type=Path,
        help="COLMAP sparse/0 folder; auto-discovers twin/work/**/sparse/0",
    )
    parser.add_argument("--no-colmap", action="store_true")
    parser.add_argument(
        "--colmap-unit-m",
        type=float,
        default=1.0,
        help="Known metres per COLMAP unit; W4 must supply scale",
    )
    parser.add_argument(
        "--twin-transform",
        type=Path,
        help="JSON 4x4 T_twin_colmap, applied after conversion to metres",
    )
    parser.add_argument("--relative", action="store_true")
    parser.add_argument(
        "--relative-scale-m",
        type=float,
        default=5,
        help="Assumed median depth in relative fallback",
    )
    parser.add_argument("--model", default=METRIC_MODEL)
    args = parser.parse_args()
    if (
        min(
            args.every_s,
            args.max_frames,
            args.max_width,
            args.stride,
            args.voxel_m,
            args.colmap_unit_m,
            args.relative_scale_m,
            args.max_depth_m,
        )
        <= 0
    ):
        parser.error("Sampling, scale and depth limits must be positive")
    frames = video_frames(
        args.video, args.every_s, args.max_frames, args.max_width, args.work / "frames"
    )
    model_path = None if args.no_colmap else args.colmap or find_model()
    cameras: dict[int, Camera] = {}
    poses: dict[str, Pose] = {}
    sparse: dict[int, Array] = {}
    if model_path:
        cameras, poses, sparse = read_model(model_path)
    matrix = (
        np.asarray(json.loads(args.twin_transform.read_text()), dtype=float)
        if args.twin_transform
        else None
    )
    if matrix is not None and matrix.shape != (4, 4):
        parser.error("Twin transform must be a 4x4 matrix")
    estimator = DepthEstimator(args.relative_scale_m, args.model, args.relative)
    clouds: list[Array] = []
    colors_list: list[Array] = []
    records: list[dict[str, Any]] = []
    args.work.mkdir(parents=True, exist_ok=True)
    for name, rgb, timestamp in frames:
        depth = estimator.predict(rgb)
        np.save(args.work / f"{Path(name).stem}_depth.npy", depth.astype(np.float32))
        h, w = depth.shape
        intrinsics = approximate_intrinsics(w, h, args.hfov_deg)
        if args.intrinsics:
            calib = json.loads(args.intrinsics.read_text())
            sx, sy = w / calib["width"], h / calib["height"]
            intrinsics = np.array(
                [
                    [calib["fx"] * sx, 0, calib["cx"] * sx],
                    [0, calib["fy"] * sy, calib["cy"] * sy],
                    [0, 0, 1],
                ]
            )
        pose = poses.get(name)
        record: dict[str, Any] = {
            "image": name,
            "timestamp_s": timestamp,
            "model": estimator.model,
            "relative": estimator.relative,
            "registration": "assumed_camera_pose",
        }
        if pose:
            camera = cameras[pose.camera_id]
            intrinsics = camera.intrinsics(w, h)
            ratio, matches = sparse_depth_scale(depth, pose, camera, sparse)
            depth *= ratio * args.colmap_unit_m
            points, colors = back_project(
                depth, rgb, intrinsics, args.stride, args.max_depth_m
            )
            pose_matrix = pose.camera_to_world()
            pose_matrix[:3, 3] *= args.colmap_unit_m
            points = transform_points(points, pose_matrix)
            if matrix is not None:
                points = transform_points(points, matrix)
            record.update(
                registration="twin_transform"
                if matrix is not None
                else "colmap_frame_unregistered",
                sparse_depth_ratio=ratio,
                sparse_matches=matches,
                colmap_unit_m=args.colmap_unit_m,
                camera_model=camera.model,
                distortion="ignored; prefer COLMAP undistorted images/PINHOLE",
            )
            clouds.append(points)
            colors_list.append(colors)
        else:
            points, colors = back_project(
                depth, rgb, intrinsics, args.stride, args.max_depth_m
            )
            # Only a display pose: right-handed X forward, Y left, Z up.
            assumed = np.array(
                [
                    [0, 0, 1, 0],
                    [-1, 0, 0, 0],
                    [0, -1, 0, args.camera_height_m],
                    [0, 0, 0, 1],
                ],
                dtype=float,
            )
            points = transform_points(points, assumed)
        record["intrinsics"] = intrinsics.tolist()
        record["depth_median_m"] = float(
            np.median(depth[np.isfinite(depth) & (depth > 0)])
        )
        frame_out = (
            args.out if len(frames) == 1 else args.out / f"frame_{len(records):06d}"
        )
        export_cloud(
            points,
            colors,
            frame_out,
            "video_monocular",
            args.voxel_m,
            extra={**record, "measured_lidar": False},
        )
        records.append(record)
        print(json.dumps(record), file=sys.stderr)
    # Never fuse unrelated camera-local clouds without motion estimates.
    if clouds:
        final_points, final_colors = np.concatenate(clouds), np.concatenate(colors_list)
        registration = (
            "twin_transform" if matrix is not None else "colmap_frame_unregistered"
        )
    else:
        final_points, final_colors = points, colors
        registration = "assumed_camera_pose"
    result = export_cloud(
        final_points,
        final_colors,
        args.out,
        "video_monocular",
        args.voxel_m,
        extra={
            "model": estimator.model,
            "relative": estimator.relative,
            "measured_lidar": False,
            "fused_frames": len(clouds),
            "registration": registration,
            "frames": records,
            "warning": "Learned depth, not LiDAR. Metric accuracy and site registration need validation.",
        },
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
