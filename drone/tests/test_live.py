import time

import cv2
import numpy as np
import pytest

from drone.driver import NotSupported
from drone.live import (
    LiveFeedDriver,
    NeoDriver,
    TelloDriver,
    _parse_source,
    pose_from_portal,
)


def test_source_parsing() -> None:
    assert _parse_source("2") == ("video", 2)
    assert _parse_source("rtmp://localhost/live/neo") == (
        "video",
        "rtmp://localhost/live/neo",
    )
    assert _parse_source("camera.mp4") == ("video", "camera.mp4")
    assert _parse_source("screen") == ("screen", None)
    assert _parse_source("screen:-10,20,640,480") == (
        "screen",
        (-10, 20, 640, 480),
    )
    assert _parse_source("screen", "1,2,320,240") == (
        "screen",
        (1, 2, 320, 240),
    )
    with pytest.raises(ValueError):
        _parse_source("screen", "1,2,0,240")


@pytest.mark.parametrize("crop", ["0.25,0.25,0.5,0.5", "8,6,32,24"])
def test_live_feed_reads_generated_mp4(tmp_path, crop: str) -> None:
    filename = tmp_path / "small.mp4"
    writer = cv2.VideoWriter(
        str(filename), cv2.VideoWriter_fourcc(*"mp4v"), 10, (64, 48)
    )
    if not writer.isOpened():
        pytest.skip("OpenCV MP4 writer is unavailable")
    for index in range(6):
        writer.write(np.full((48, 64, 3), index * 30, dtype=np.uint8))
    writer.release()

    driver = LiveFeedDriver(str(filename), {"portals": []}, fps=30, crop=crop)
    try:
        deadline = time.monotonic() + 3
        frame = None
        while time.monotonic() < deadline:
            frame = driver.latest_frame()
            if frame is not None:
                break
            time.sleep(0.02)
        assert frame is not None
        assert frame.source == "live"
        assert frame.image.shape == (24, 32, 3)
        assert next(driver.video_frames()).image.shape == (24, 32, 3)
    finally:
        driver.close()


@pytest.mark.parametrize("driver_type", [LiveFeedDriver, NeoDriver, TelloDriver])
def test_flight_commands_are_not_supported(driver_type) -> None:
    driver = (
        LiveFeedDriver("0", {"portals": []})
        if driver_type is LiveFeedDriver
        else driver_type()
    )
    try:
        for command in (
            driver.takeoff,
            driver.land,
            lambda: driver.send_velocity(0, 0, 0, 0),
        ):
            with pytest.raises(NotSupported):
                command()
    finally:
        if driver_type is LiveFeedDriver:
            driver.close()


def test_pose_from_portal_round_trip() -> None:
    width, height = 1280, 720
    portal = {"id": "P2", "size_m": 0.3, "T_twin_portal": np.eye(4).ravel().tolist()}
    fx = 0.8 * width
    camera_matrix = np.array(
        [[fx, 0, width / 2], [0, fx, height / 2], [0, 0, 1]], dtype=np.float64
    )
    object_points = np.array(
        [
            [-0.15, 0.15, 0],
            [0.15, 0.15, 0],
            [0.15, -0.15, 0],
            [-0.15, -0.15, 0],
        ],
        dtype=np.float64,
    )
    rvec = np.array([3.10, 0.04, 0.07], dtype=np.float64)
    tvec = np.array([0.12, -0.03, 2.0], dtype=np.float64)
    corners, _ = cv2.projectPoints(
        object_points, rvec, tvec, camera_matrix, np.zeros(5)
    )
    rotation, _ = cv2.Rodrigues(rvec)
    expected_position = -rotation.T @ tvec
    expected_forward = rotation.T @ np.array([0.0, 0.0, 1.0])
    expected_yaw = np.degrees(np.arctan2(expected_forward[1], expected_forward[0]))

    actual = pose_from_portal(corners.reshape(4, 2), portal, (width, height))

    assert np.linalg.norm(np.asarray(actual[:3]) - expected_position) < 0.05
    assert abs((actual[3] - expected_yaw + 180) % 360 - 180) < 1.0
