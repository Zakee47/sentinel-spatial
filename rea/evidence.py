#!/usr/bin/env python3
"""Extract only names from an APK, a decoded manifest and REA's class list."""

import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

apk, manifest, class_list, native_identifiers, architecture_identifiers, output = map(
    Path, sys.argv[1:]
)
output.mkdir(parents=True, exist_ok=True)
android = "{http://schemas.android.com/apk/res/android}"
root = ET.parse(manifest).getroot()
app = root.find("application")


def write(name, lines):
    lines = list(lines)
    if len(lines) >= 200:
        raise ValueError(f"{name}: too many lines ({len(lines)})")
    (output / name).write_text("\n".join(lines) + "\n")


write(
    "permissions.txt",
    (e.get(android + "name") for e in root.findall("uses-permission")),
)
write(
    "features.txt",
    (
        e.get(android + "name") + " required=" + e.get(android + "required", "true")
        for e in root.findall("uses-feature")
        if e.get(android + "name")
    ),
)
services = [e.get(android + "name") for e in app.findall("service")]
write("services.txt", services)
terms = re.compile(r"wifi|usb|connection|connect|live|stream", re.IGNORECASE)
components = []
for e in app:
    if e.tag not in ("activity", "service", "receiver"):
        continue
    name = e.get(android + "name", "")
    actions = [x.get(android + "name", "") for x in e.findall("./intent-filter/action")]
    if (
        "firmware" not in name.lower()
        and name.startswith(("com.uav.", "com.dji."))
        and (terms.search(name) or any(terms.search(x) for x in actions))
    ):
        components.append(e.tag + " " + name)
        components.extend("  " + x for x in actions if terms.search(x))
write("components.txt", components)

with zipfile.ZipFile(apk) as z:
    libraries = sorted(
        x for x in z.namelist() if re.fullmatch(r"lib/arm64-v8a/[^/]+", x)
    )
    for index in range(0, len(libraries), 120):
        write(f"arm64-libs-{index // 120 + 1}.txt", libraries[index : index + 120])
    dex = z.read("classes.dex")
    tokens = {
        x.decode("ascii") for x in re.findall(rb"[A-Za-z_][A-Za-z0-9_.$/;]{3,}", dex)
    }

for term in ("rtmp", "livestream", "neo", "wifi", "ocusync", "virtualstick"):
    matches = sorted(x for x in tokens if term in x.lower())
    write(f"dex-strings-{term}.txt", matches[:180] if matches else ["(no matches)"])

classes = class_list.read_text().splitlines()[2:]
matches = [
    x
    for x in classes
    if re.search(
        r"dji|uav|wifi|usb|rtmp|stream|neo|ocusync|virtualstick|duml|sdk|codec",
        x,
        re.IGNORECASE,
    )
]
write("rea-class-matches.txt", matches if matches else ["(no matches)"])

depth_pattern = re.compile(
    r"obstacle|perception|vision|radar|tof|lidar|depth|avoidance|omni|apas|bypass",
    re.IGNORECASE,
)
depth = ["[REA top-level class names]"]
depth_classes = [x for x in classes if depth_pattern.search(x)]
depth.extend(depth_classes or ["(no matches)"])
depth.append("[classes.dex identifier strings; substring matches may be unrelated]")
depth.extend(sorted(x for x in tokens if depth_pattern.search(x)) or ["(no matches)"])
depth.append("[manifest flight-record components]")
depth.extend(
    e.tag + " " + e.get(android + "name")
    for e in app
    if re.search("flightrecord", e.get(android + "name", ""), re.IGNORECASE)
)
depth.append("[selected native identifier strings; not evidence of execution]")
selected = re.compile(
    r"^(?:AllDirectionsObstacleDistanceInfo(?:ByteArray|Converter)|AndroidSdrFlightOSDTopObstacleVisionShellModel|BaseFlightOSDTopObstacleVisionShell|ObstacleDetectionSector|ObstacleDetectionSectorWarning|ObstacleDirection|PerceptionObstacleDistances|PerceptionState|RadarObstacleInfo|ObstacleAvoidanceV1|ObstacleWarningMinDistance|OmniDownRadarDistance|OmniHorizontalRadarDistance|OmniUpRadarDistance|OmnidirectionalObstacleAvoidance|OmnidirectionalRadarStatus|horizontalObstacleDistances|downObstacleDistance|upObstacleDistance|obstacleDistanceInMeters|N3uav3sdk3key18PackObserverHelperINS_4core33perception_birdview_distance_pushEEE|_ZN3uav12FlightRecord18FlightRecordEngine23UpdateObstacleDistancesEPvm|_ZN3uav12FlightRecord18FlightRecordEngine31EnablePerceptionGroupDataRecordEv)$"
)
for line in native_identifiers.read_text().splitlines():
    library, name = line.split(" ", 1)
    if selected.fullmatch(name):
        depth.append(line)
write("depth.txt", depth)

architecture_names = {
    "NEO2",
    "OCUSYNC",
    "OcuSyncLink",
    "Luav/ksdk/keyvalue/key/UAVOcuSyncKey",
    "Luav/sdk/keyvalue/key/UAVOcuSyncKey",
    "KeySendVirtualStickFlightControlData",
    "KeyVirtualStickControlModeEnabled",
    "Lcom/uav/livestream/LiveStreamSession",
    "Lcom/uav/livestream/core/audio/LiveStreamAudioEncoder",
    "Lcom/uav/livestream/core/video/LiveStreamVideoEncoder",
    "Lcom/uav/component/fpv/base/debug/VirtualStickDebugConfig",
    "Lcom/uav/component/fpv/mvi/slots/widgets/virtualcontrol/MviVirtualStickView",
}
write(
    "native-architecture-strings.txt",
    (
        "lib/arm64-v8a/libdatajar.so " + x
        for x in architecture_identifiers.read_text().splitlines()
        if x in architecture_names
    ),
)
