"""ONVIF camera discovery + stream URI lookup.

python -m cctv.onvif_discover                       # WS-Discovery probe on the LAN
python -m cctv.onvif_discover --ip 192.168.1.64     # RTSP + snapshot URIs (needs onvif-zeep)
    credentials from env ONVIF_USER / ONVIF_PASS (never on the command line in demos)
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import time
import uuid

WSD_ADDR = ("239.255.255.250", 3702)

PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
 xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
 <e:Header>
  <w:MessageID>uuid:{msg_id}</w:MessageID>
  <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
  <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
 </e:Header>
 <e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>
</e:Envelope>"""

_XADDRS = re.compile(r"<[^>]*XAddrs>([^<]+)</[^>]*XAddrs>")
_SCOPES = re.compile(r"<[^>]*Scopes[^>]*>([^<]+)</[^>]*Scopes>")


def build_probe(msg_id: str | None = None) -> bytes:
    return PROBE.format(msg_id=msg_id or uuid.uuid4()).encode()


def parse_probe_match(xml: str) -> dict:
    xaddrs = _XADDRS.search(xml)
    scopes = _SCOPES.search(xml)
    sc = scopes.group(1).split() if scopes else []

    def scope(key: str) -> str | None:
        for s in sc:
            if f"/{key}/" in s:
                return s.rsplit("/", 1)[-1].replace("%20", " ")
        return None

    return {
        "xaddrs": xaddrs.group(1).split() if xaddrs else [],
        "name": scope("name"),
        "hardware": scope("hardware"),
        "location": scope("location"),
    }


def discover(timeout: float = 3.0) -> list[dict]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(0.5)
    sock.sendto(build_probe(), WSD_ADDR)
    found: dict[str, dict] = {}
    end = time.time() + timeout
    while time.time() < end:
        try:
            data, (ip, _) = sock.recvfrom(65535)
        except TimeoutError:
            continue
        except OSError:
            break
        info = parse_probe_match(data.decode(errors="ignore"))
        info["ip"] = ip
        found[ip] = info
    sock.close()
    return list(found.values())


def stream_uris(ip: str, user: str, password: str, port: int = 80) -> list[dict]:
    try:
        from onvif import ONVIFCamera  # onvif-zeep
    except ImportError as e:
        raise SystemExit("pip install onvif-zeep to query stream URIs") from e
    cam = ONVIFCamera(ip, port, user, password)
    media = cam.create_media_service()
    out = []
    for prof in media.GetProfiles():
        req = media.create_type("GetStreamUri")
        req.ProfileToken = prof.token
        req.StreamSetup = {"Stream": "RTP-Unicast", "Transport": {"Protocol": "RTSP"}}
        rtsp = media.GetStreamUri(req).Uri
        try:
            snap = media.GetSnapshotUri({"ProfileToken": prof.token}).Uri
        except Exception:  # noqa: BLE001 - many cameras don't implement it
            snap = None
        out.append({"profile": prof.Name, "token": prof.token, "rtsp": rtsp, "snapshot": snap})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=None)
    ap.add_argument("--port", type=int, default=80)
    ap.add_argument("--timeout", type=float, default=3.0)
    a = ap.parse_args()
    if a.ip:
        for p in stream_uris(a.ip, os.environ.get("ONVIF_USER", "admin"), os.environ.get("ONVIF_PASS", ""), a.port):
            print(f"{p['profile']:<20} rtsp={p['rtsp']}  snapshot={p['snapshot']}")
        return
    cams = discover(a.timeout)
    if not cams:
        print("no ONVIF cameras answered (same L2 network? multicast allowed?)")
    for c in cams:
        print(f"{c['ip']:<16} {c['name'] or '?':<24} {c['hardware'] or '':<16} {' '.join(c['xaddrs'])}")


if __name__ == "__main__":
    main()
