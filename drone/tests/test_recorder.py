import json
import threading
import time

import numpy as np

from drone.driver import Frame
from drone.recorder import FrameRecorder


def frame(ts: float, value: int = 10) -> Frame:
    return Frame(ts=ts, image=np.full((24, 32, 3), value, dtype=np.uint8), source="live")


def test_recorder_writes_sampled_jpegs_and_manifest(tmp_path) -> None:
    recorder = FrameRecorder(tmp_path / "recording", "screen:0,0,32,24", "0,0,32,24")
    try:
        assert recorder.offer(frame(1.0))
        assert not recorder.offer(frame(1.1))
        assert recorder.offer(frame(1.5))
    finally:
        stats = recorder.close()

    directory = tmp_path / "recording"
    assert sorted(path.name for path in (directory / "frames").glob("*.jpg")) == [
        "000001.jpg",
        "000002.jpg",
    ]
    metadata = json.loads((directory / "record.json").read_text())
    assert metadata["source"] == "screen:0,0,32,24"
    assert metadata["crop"] == "0,0,32,24"
    assert metadata["frame_count"] == stats["frame_count"] == 2
    assert metadata["dropped_frames"] == 0


def test_manifest_redacts_stream_credentials(tmp_path) -> None:
    recorder = FrameRecorder(
        tmp_path / "recording",
        "rtmp://operator:secret@example.test/live/stream-key?token=secret",
    )
    recorder.close()

    manifest = json.loads((tmp_path / "recording" / "record.json").read_text())
    assert manifest["source"] == "rtmp://example.test/live/[REDACTED]"
    assert "secret" not in json.dumps(manifest)
    assert "stream-key" not in json.dumps(manifest)


def test_full_queue_drops_without_blocking(monkeypatch, tmp_path) -> None:
    entered_writer = threading.Event()
    release_writer = threading.Event()
    original_jpeg = Frame.jpeg

    def slow_jpeg(self: Frame, quality: int = 85) -> bytes:
        entered_writer.set()
        release_writer.wait(timeout=2)
        return original_jpeg(self, quality)

    monkeypatch.setattr(Frame, "jpeg", slow_jpeg)
    recorder = FrameRecorder(tmp_path / "recording", "camera.mp4", queue_size=1)
    assert recorder.offer(frame(1.0))
    assert entered_writer.wait(timeout=1)
    assert recorder.offer(frame(2.0))

    started = time.monotonic()
    assert not recorder.offer(frame(3.0))
    assert time.monotonic() - started < 0.1
    release_writer.set()
    stats = recorder.close()
    assert stats["frame_count"] == 2
    assert stats["dropped_frames"] == 1
