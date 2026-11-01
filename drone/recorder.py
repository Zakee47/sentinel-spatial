from __future__ import annotations

import json
import logging
import queue
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import cv2

from drone.driver import Frame
from drone.source import safe_source

log = logging.getLogger("drone.recorder")
_STOP = object()


class FrameRecorder:
    """Sample live frames into a bounded background writer."""

    def __init__(
        self,
        directory: str | Path,
        source: str,
        crop: str | None = None,
        every_s: float = 0.5,
        queue_size: int = 8,
    ) -> None:
        if every_s <= 0:
            raise ValueError("record interval must be positive")
        if queue_size <= 0:
            raise ValueError("record queue size must be positive")
        self.directory = Path(directory).expanduser().resolve()
        self.frames_dir = self.directory / "frames"
        self.directory.mkdir(parents=True, exist_ok=True)
        if self.frames_dir.exists() and any(self.frames_dir.iterdir()):
            raise FileExistsError(f"Recording frames directory is not empty: {self.frames_dir}")
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.source = safe_source(source)
        self.crop = crop
        self.every_s = every_s
        self._queue: queue.Queue[Frame | object] = queue.Queue(maxsize=queue_size)
        self._lock = threading.Lock()
        self._closed = False
        self._last_sample_ts: float | None = None
        self._last_frame_ts: float | None = None
        self._frame_count = 0
        self._dropped_frames = 0
        self._write_errors = 0
        self._started_at = datetime.now(UTC)
        self._started_monotonic = time.monotonic()
        self._thread = threading.Thread(
            target=self._write_loop, name="live-frame-recorder", daemon=True
        )
        self._thread.start()

    def offer(self, frame: Frame) -> bool:
        """Queue a due frame without waiting for disk or image encoding."""
        with self._lock:
            if self._closed:
                return False
            if self._last_frame_ts is not None and frame.ts <= self._last_frame_ts:
                return False
            self._last_frame_ts = frame.ts
            if self._last_sample_ts is not None and frame.ts - self._last_sample_ts < self.every_s:
                return False
            self._last_sample_ts = frame.ts
            try:
                self._queue.put_nowait(frame)
                return True
            except queue.Full:
                self._dropped_frames += 1
                return False

    def close(self) -> dict[str, int]:
        with self._lock:
            if self._closed:
                return self.stats
            self._closed = True
        while self._thread.is_alive():
            try:
                self._queue.put(_STOP, timeout=0.1)
                break
            except queue.Full:
                continue
        self._thread.join()
        ended_at = datetime.now(UTC)
        video_path = self.directory / "flight.mp4"
        manifest = {
            "started_at": self._started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_s": round(time.monotonic() - self._started_monotonic, 3),
            "source": self.source,
            "crop": self.crop,
            "record_every_s": self.every_s,
            "frame_count": self._frame_count,
            "dropped_frames": self._dropped_frames,
            "write_errors": self._write_errors,
            "frames_dir": str(self.frames_dir),
            "video": str(video_path) if video_path.is_file() and video_path.stat().st_size else None,
        }
        (self.directory / "record.json").write_text(json.dumps(manifest, indent=2) + "\n")
        return self.stats

    @property
    def stats(self) -> dict[str, int]:
        return {
            "frame_count": self._frame_count,
            "dropped_frames": self._dropped_frames,
            "write_errors": self._write_errors,
        }

    def _write_loop(self) -> None:
        writer: cv2.VideoWriter | None = None
        writer_size: tuple[int, int] | None = None
        video_attempted = False
        video_fps = max(1.0, min(10.0, 1.0 / self.every_s))
        try:
            while True:
                frame = self._queue.get()
                try:
                    if frame is _STOP:
                        return
                    assert isinstance(frame, Frame)
                    try:
                        payload = frame.jpeg(quality=90)
                        filename = self.frames_dir / f"{self._frame_count + 1:06d}.jpg"
                        filename.write_bytes(payload)
                        self._frame_count += 1
                        if not video_attempted:
                            video_attempted = True
                            size = (frame.image.shape[1], frame.image.shape[0])
                            candidate = cv2.VideoWriter(
                                str(self.directory / "flight.mp4"),
                                cv2.VideoWriter_fourcc(*"mp4v"),
                                video_fps,
                                size,
                            )
                            if candidate.isOpened():
                                writer = candidate
                                writer_size = size
                            else:
                                candidate.release()
                                log.warning("MP4 writer unavailable; JPEG frames remain primary")
                        if writer is not None:
                            image = frame.image
                            if writer_size and (image.shape[1], image.shape[0]) != writer_size:
                                image = cv2.resize(
                                    image,
                                    writer_size,
                                )
                            writer.write(image)
                    except Exception as exc:  # noqa: BLE001 - recording must not break the flight loop
                        self._write_errors += 1
                        log.warning("Could not write a sampled frame: %s", exc)
                finally:
                    self._queue.task_done()
        finally:
            if writer is not None:
                writer.release()
