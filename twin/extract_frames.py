"""Sample bounded, uniformly spaced frames for an offline COLMAP reconstruction."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path


def video_duration(video: Path) -> float | None:
    if shutil.which("ffprobe") is None:
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video.resolve()),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        duration = float(result.stdout.strip())
        return duration if math.isfinite(duration) and duration > 0 else None
    except (subprocess.SubprocessError, ValueError):
        return None


def filter_blurry_frames(out: Path, threshold: float) -> list[dict[str, object]]:
    import cv2

    scores = []
    for path in sorted(out.glob("frame_*.jpg")):
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        score = float(cv2.Laplacian(image, cv2.CV_64F).var()) if image is not None else 0.0
        keep = image is not None and score >= threshold
        scores.append({"frame": path.name, "laplacian_variance": score, "kept": keep})
        if not keep:
            path.unlink()
    return scores


def extract(
    video: Path,
    out: Path,
    fps: float = 2.0,
    max_frames: int = 160,
    max_width: int = 1600,
    blur_threshold: float = 50.0,
) -> int:
    if not video.is_file():
        raise FileNotFoundError(video)
    if not math.isfinite(fps) or fps <= 0 or max_frames < 3 or max_width < 64:
        raise ValueError("fps > 0, max_frames >= 3 and max_width >= 64 required")
    if not math.isfinite(blur_threshold) or blur_threshold < 0:
        raise ValueError("blur_threshold must be finite and nonnegative")
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("Install ffmpeg first")
    if out.exists() and any(out.iterdir()):
        raise ValueError(f"{out} must be empty (avoid mixing camera sequences)")
    out.mkdir(parents=True, exist_ok=True)
    duration = video_duration(video)
    sample_fps = min(fps, max_frames / duration) if duration else fps
    print(
        f"Sampling at {sample_fps:.3f} fps (requested {fps:g}); max width {max_width}px", flush=True
    )
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-i",
            str(video.resolve()),
            "-vf",
            f"fps={sample_fps},scale='min({max_width},iw)':-2",
            "-frames:v",
            str(max_frames),
            "-q:v",
            "2",
            str(out / "frame_%06d.jpg"),
        ],
        check=True,
        timeout=300,
    )
    scores = filter_blurry_frames(out, blur_threshold)
    count = len(list(out.glob("frame_*.jpg")))
    (out.parent / "frames.json").write_text(
        json.dumps(
            {
                "input": video.name,
                "fps": fps,
                "sample_fps": sample_fps,
                "duration_s": duration,
                "max_width": max_width,
                "frame_count": count,
                "sampled_count": len(scores),
                "blur_threshold": blur_threshold,
                "rejected_count": len(scores) - count,
                "frames": scores,
                "video_uploaded": False,
            },
            indent=2,
        )
        + "\n"
    )
    print(
        f"Kept {count}/{len(scores)} frames; rejected {len(scores) - count} blurry/unreadable frames "
        f"(Laplacian variance < {blur_threshold:g})",
        flush=True,
    )
    if count < 3:
        raise RuntimeError(
            f"Only {count} sharp frames remain; need at least 3. "
            "Film slowly with more texture/light; see frames.json for blur scores. "
            "TWIN_BLUR_THRESHOLD=0 disables the heuristic for low-contrast scenes."
        )
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--out", type=Path, default=Path("twin/work/frames"))
    parser.add_argument("--fps", type=float, default=2.0)
    parser.add_argument("--max-frames", type=int, default=160)
    parser.add_argument("--max-width", type=int, default=1600)
    parser.add_argument("--blur-threshold", type=float, default=50.0)
    args = parser.parse_args()
    print(
        f"Extracted {extract(args.video, args.out, args.fps, args.max_frames, args.max_width, args.blur_threshold)} frames"
    )


if __name__ == "__main__":
    main()
