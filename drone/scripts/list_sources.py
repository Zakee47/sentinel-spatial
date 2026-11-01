#!/usr/bin/env python3
"""List OpenCV camera indices and desktop monitor geometries."""

import argparse

import cv2
import mss


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-index", type=int, default=10)
    args = parser.parse_args()
    print("OpenCV camera indices:")
    for index in range(args.max_index + 1):
        capture = cv2.VideoCapture(index)
        if capture.isOpened():
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f"  {index}: opens ({width}x{height})")
        capture.release()
    print("MSS monitors:")
    with mss.mss() as capture:
        for index, monitor in enumerate(capture.monitors):
            if index == 0:
                print(f"  {index}: all monitors {monitor}")
            else:
                print(
                    f"  {index}: left={monitor['left']} top={monitor['top']} "
                    f"width={monitor['width']} height={monitor['height']}"
                )


if __name__ == "__main__":
    main()
