"""Re-serve the latest frame of each configured CCTV camera (port 8090).

GET /cameras                      -> list + health
GET /cameras/<id>/snapshot.jpg    -> latest JPEG
GET /cameras/<id>/mjpeg           -> multipart/x-mixed-replace MJPEG stream
GET /health

python -m cctv.snapshot_server [--config cctv/cameras.local.yaml] [--port 8090]
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import AsyncIterator

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from cctv.sources import CCTVSource, load_cameras, open_source

BOUNDARY = "frame"


def encode(frame, quality: int = 80, max_width: int = 1280) -> bytes:
    h, w = frame.shape[:2]
    if w > max_width:
        frame = cv2.resize(frame, (max_width, int(h * max_width / w)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return buf.tobytes() if ok else b""


def create_app(sources: dict[str, CCTVSource]) -> FastAPI:
    app = FastAPI(title="Sentinel CCTV snapshots")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

    def get(cam_id: str) -> CCTVSource:
        if cam_id not in sources:
            raise HTTPException(404, f"unknown camera {cam_id}")
        return sources[cam_id]

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "cameras": len(sources)}

    @app.get("/cameras")
    def cameras() -> list[dict]:
        return [
            {
                "id": cid,
                "uri": s.info.redacted,
                "snapshot_url": f"/cameras/{cid}/snapshot.jpg",
                "feed_url": f"/cameras/{cid}/mjpeg",
                **s.health.as_dict(),
            }
            for cid, s in sources.items()
        ]

    @app.get("/cameras/{cam_id}/snapshot.jpg")
    def snapshot(cam_id: str) -> Response:
        frame = get(cam_id).latest()
        if frame is None:
            raise HTTPException(503, "no frame yet")
        return Response(encode(frame), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/cameras/{cam_id}/mjpeg")
    async def mjpeg(cam_id: str, fps: float = 10.0) -> StreamingResponse:
        src = get(cam_id)
        period = 1.0 / max(0.5, min(fps, 30.0))

        async def gen() -> AsyncIterator[bytes]:
            last = None
            while True:
                t0 = time.time()
                frame = src.latest()
                ts = src.health.last_frame_ts
                if frame is not None and ts != last:
                    last = ts
                    jpg = encode(frame, quality=70, max_width=960)
                    yield (
                        f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpg)}\r\n\r\n".encode()
                        + jpg
                        + b"\r\n"
                    )
                await asyncio.sleep(max(0.0, period - (time.time() - t0)))

        return StreamingResponse(gen(), media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}")

    @app.on_event("shutdown")
    def _close() -> None:
        for s in sources.values():
            s.release()

    return app


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None, help="cameras yaml (default cameras.local.yaml or cameras.example.yaml)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8090)
    a = ap.parse_args()
    cams = load_cameras(a.config)
    if not cams:
        raise SystemExit("no cameras configured")
    sources = {cid: open_source(uri, loop_files=True) for cid, uri in cams.items()}
    import uvicorn

    uvicorn.run(create_app(sources), host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
