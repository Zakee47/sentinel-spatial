"""Fit a proper Sim(3) from portal corners or manually picked 3D correspondences."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from twin.cloud import Cloud, read_cloud


def similarity(source: Cloud, target: Cloud) -> tuple[Cloud, float]:
    source, target = np.asarray(source, dtype=float), np.asarray(target, dtype=float)
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3 or len(source) < 3:
        raise ValueError("Need >=3 corresponding Nx3 source and target points")
    if not np.isfinite(source).all() or not np.isfinite(target).all():
        raise ValueError("Correspondences must be finite")
    a, b = source - source.mean(axis=0), target - target.mean(axis=0)
    if np.linalg.matrix_rank(a) < 2 or np.linalg.matrix_rank(b) < 2:
        raise ValueError("Picked points must not be collinear")
    u, singular, vt = np.linalg.svd(b.T @ a / len(a))
    sign = np.ones(3)
    sign[-1] = np.linalg.det(u @ vt)
    rotation = u @ np.diag(sign) @ vt
    scale = (singular * sign).sum() / np.mean(np.sum(a * a, axis=1))
    if scale <= 0:
        raise ValueError("Similarity scale must be positive")
    transform = np.eye(4)
    transform[:3, :3] = scale * rotation
    transform[:3, 3] = target.mean(axis=0) - scale * rotation @ source.mean(axis=0)
    residual = np.linalg.norm(source @ transform[:3, :3].T + transform[:3, 3] - target, axis=1)
    return transform, float(np.sqrt(np.mean(residual**2)))


def portal_corners(portal: dict[str, Any]) -> Cloud:
    """QR ordering: top-left, top-right, bottom-right, bottom-left, viewed head-on."""
    s = portal["size_m"] / 2
    local = np.array([[-s, s, 0], [s, s, 0], [s, -s, 0], [-s, -s, 0]])
    transform = np.asarray(portal["T_twin_portal"], dtype=float).reshape(4, 4)
    return local @ transform[:3, :3].T + transform[:3, 3]


def correspondences(data: dict[str, Any], site: dict[str, Any]) -> tuple[Cloud, Cloud]:
    source, target = [], []
    for pair in data.get("pairs", []):
        source.append(pair["colmap"])
        target.append(pair["twin"])
    portals = {p["id"]: p for p in site["portals"]}
    for detected in data.get("portals", []):
        if np.asarray(detected["colmap_corners"]).shape != (4, 3):
            raise ValueError("Each portal needs 4 ordered COLMAP corners")
        source.extend(detected["colmap_corners"])
        target.extend(portal_corners(portals[detected["id"]]).tolist())
    return np.asarray(source), np.asarray(target)


def apply_transform(points: Cloud, transform: Cloud) -> Cloud:
    result = points.copy()
    result[:, :3] = points[:, :3] @ transform[:3, :3].T + transform[:3, 3]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument(
        "--alignment",
        type=Path,
        help="JSON of manual pairs or triangulated portal corners",
    )
    parser.add_argument(
        "--model",
        type=Path,
        help="COLMAP TXT model, needed for automatic QR triangulation",
    )
    parser.add_argument(
        "--images",
        type=Path,
        help="Frames used by COLMAP, needed for automatic QR triangulation",
    )
    parser.add_argument("--site", type=Path, default=Path("config/site.yaml"))
    parser.add_argument("--out", type=Path, default=Path("twin/work/anchored.npy"))
    parser.add_argument("--max-rmse-m", type=float, default=0.15)
    args = parser.parse_args()
    site = yaml.safe_load(args.site.read_text())
    if args.alignment:
        data = json.loads(args.alignment.read_text())
        method = "manual" if data.get("pairs") else "portal_corners"
    elif args.model and args.images:
        from twin.portals import detect_portals

        data = detect_portals(args.model, args.images, site)
        method = "qr_multiview"
    else:
        parser.error(
            "Supply --alignment or both --model and --images; metric scale cannot be guessed"
        )
    source, target = correspondences(data, site)
    transform, rmse = similarity(source, target)
    if rmse > args.max_rmse_m:
        raise ValueError(f"Anchor RMSE {rmse:.3f}m exceeds {args.max_rmse_m}m")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    np.save(args.out, apply_transform(read_cloud(args.input), transform))
    report = {
        "method": method,
        "T_twin_colmap": transform.tolist(),
        "rmse_m": rmse,
        "correspondence_count": len(source),
        "scale": float(np.linalg.norm(transform[:3, 0])),
    }
    args.out.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
