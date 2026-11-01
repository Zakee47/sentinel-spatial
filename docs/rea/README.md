# DJI Fly architecture inventory

## Artifact and boundaries

DJI's [Fly download page](https://www.dji.com/downloads/djiapp/dji-fly) links version **1.21.18** to the [official download landing page](https://service-adhoc.dji.com/download/app/android/3b03cb95-bc4b-4b62-b4ab-9cf977d77309). That page supplied a signed, expiring URL on `terra-2-g.djicdn.com` with path `/a81c919a2cba4e93a2147801711c04d1/1793008319309-DJIFly-1.21.18.1003(3132440)-android-release-261023-sec.apk`. Obtain fresh query parameters from the landing page rather than reusing an expired signed URL.

`~/dji/dji-fly-1.21.18.apk`: SHA-256 `a4d0bcfb6be9731bcc07dc66b67a3492c770ceda9d0fa94ec247df2889be8a0d`; package `dji.go.v5`, version code 3132440, min SDK 24, target SDK 34. The APK stays outside this repo. No app source bodies, firmware analysis, or authentication/encryption circumvention are included.

## Setup and commands

The [REA README](https://github.com/morluto/rea) describes `npx rea-agents setup`; `rea/setup.sh` performs noninteractive Devin setup, installs the latest JADX zip under `~/tools/jadx`, and installs REA's documented jadx-headless-mcp 0.7.1 bridge with its published SHA-256 check. The script prints the PATH export and MCP configuration; execute the printed export in the calling shell, and restart the MCP client after registration. It refuses to overwrite a different existing JADX version. Setup installed REA 6.8.0; the manual snippet uses `@latest`, so a future install may differ.

Commands below were run from the repository root unless otherwise noted. Download used the official landing page and CDN only:

```bash
./rea/setup.sh
url=$(curl -fsSL 'https://service-adhoc.dji.com/download/app/android/3b03cb95-bc4b-4b62-b4ab-9cf977d77309' | python3 -c 'import sys,re,html; print(html.unescape(re.search(r"https?://terra-2-g\.djicdn\.com/[^\"\x27<> ]+\.apk[^\"\x27<> ]*",sys.stdin.read()).group()))')
curl -fL --retry 2 "$url" -o /home/ubuntu/dji/dji-fly-1.21.18.apk
sha256sum /home/ubuntu/dji/dji-fly-1.21.18.apk
```

REA was invoked from trusted `/home/ubuntu`, not the APK directory. These are suitable demo commands:

```bash
cd /home/ubuntu
export REA_JADX_MCP_JAR=/home/ubuntu/tools/jadx-headless-mcp-0.7.1-all.jar
npx --yes rea-agents@latest doctor --provider jadx --format json
npx --yes rea-agents@latest inspect-android-package /home/ubuntu/dji/dji-fly-1.21.18.apk --format json
npx --yes rea-agents@latest search-android-classes /home/ubuntu/dji/dji-fly-1.21.18.apk WiFi --format json
npx --yes rea-agents@latest search-android-classes /home/ubuntu/dji/dji-fly-1.21.18.apk dji.sdk --format json
npx --yes rea-agents@latest search-android-classes /home/ubuntu/dji/dji-fly-1.21.18.apk '' --format json | python3 -c 'import json,sys;d=json.load(sys.stdin);n=d["normalized_result"];print("total_classes:",n["total_classes"]);print("coverage:",n["coverage"]);print("\n".join(n["matches"]))' > /home/ubuntu/dji/rea-class-list.txt
/home/ubuntu/tools/jadx/bin/jadx -s -d /home/ubuntu/dji/resources /home/ubuntu/dji/dji-fly-1.21.18.apk
```

REA inspection and class search worked after supplying the bridge. Initially they failed with `capability_unavailable` because the bridge was not configured; an early attempt while the APK was downloading reported `target grew while being read` and succeeded after completion. GitHub's releases API returned 403; resolving the official latest-release redirect worked instead. `jadx -s` decoded resources/manifest only, not Java source. The remaining fallback inventory uses archive listings and ASCII identifier-like substrings (not full strings or code). Native scan and generation commands:

```bash
python3 -c 'import zipfile,re; z=zipfile.ZipFile("/home/ubuntu/dji/dji-fly-1.21.18.apk"); p=re.compile(rb"[A-Za-z_][A-Za-z0-9_.$]{3,159}"); terms=(b"obstacle",b"perception",b"vision",b"radar",b"tof",b"lidar",b"depth",b"avoidance",b"omni",b"apas",b"bypass"); out=set();
for n in z.namelist():
 if re.fullmatch(r"lib/arm64-v8a/[^/]+\.so",n):
  for m in p.finditer(z.read(n)):
   x=m.group(); low=x.lower()
   if any(t in low for t in terms): out.add(n+" "+x.decode("ascii"))
print("\n".join(sorted(out)))' > /home/ubuntu/dji/depth-native-identifiers.txt
python3 -c 'import zipfile,re;z=zipfile.ZipFile("/home/ubuntu/dji/dji-fly-1.21.18.apk");d=z.read("lib/arm64-v8a/libdatajar.so");p=re.compile(rb"[A-Za-z_][A-Za-z0-9_.$/]{3,159}");terms=(b"virtualstick",b"ocusync",b"livestream",b"liveshare",b"rtmp",b"duml",b"neo2",b"dji/sdk",b"dji/v5");s={x.group().decode() for x in p.finditer(d) if any(t in x.group().lower() for t in terms)};print("\n".join(sorted(s)))' > /home/ubuntu/dji/native-architecture-identifiers.txt
cd /home/ubuntu/sentinel-spatial
python3 rea/evidence.py /home/ubuntu/dji/dji-fly-1.21.18.apk /home/ubuntu/dji/resources/resources/AndroidManifest.xml /home/ubuntu/dji/rea-class-list.txt /home/ubuntu/dji/depth-native-identifiers.txt /home/ubuntu/dji/native-architecture-identifiers.txt docs/rea/evidence
```

## Findings and limitations

Evidence files contain bounded names only. The 210 ARM64 library paths are complete and split across two files; permissions, declared features and all services are listed. Manifest activities include `DJIAoaActivity` with `USB_ACCESSORY_ATTACHED` and Wi-Fi connection activities. USB host is optional, USB accessory required. No explicitly named DJI Wi-Fi, RC or livestream *service* was identified; activity names do not establish the RC-N3 transport. Native names include `libilink2.so`, `libilink_network.so`, `libmrtc_rtmp.so`, `libsdk_liveshare_core.so`, `libmtmd_h264streaming.so`, `libmtmd_xplat_codec.so`, `libuav_video_jni.so`, and multiple `libwab*_proto.so`. Names are not proof of runtime use or a WA-to-Neo mapping.

REA returned 984 visible top-level classes, including `dji.go.v5.R`, but no `dji.sdk` match. Its `complete` coverage is only for what the provider parsed, not proof of absent functionality. The APK's visible archive has one `classes.dex`; other identifiers occur as raw strings in native libraries. Selected `libdatajar.so` strings include `Luav/sdk/keyvalue/key/UAVOcuSyncKey`, `KeySendVirtualStickFlightControlData`, livestream encoder/session names and `NEO2`; these are strings, not REA-confirmed Java classes, product mapping, or evidence of execution. The dex identifier search for RTMP, livestream, OcuSync and virtualstick had no matches; its `neo` substring results are unrelated `PolylineOptions` names. No DUML/v1 Java packer, public MSDK or Neo 2-specific protocol path was established.

### Depth / obstacle interpretation

`evidence/depth.txt` includes all matching visible REA top-level class names and matching dex identifier substrings, plus selected native identifier strings from a 15,761-match scan of ARM64 libraries. Substring hits can be unrelated (`tof` in `OutOfBounds`, graphics `glDepthMask`); selected native names are not exhaustive. `libsdk_jni.so` contains an observer name involving `perception_birdview_distance_push` and obstacle/radar-distance keys; `libdatajar.so` contains obstacle display/distance identifiers; `libfr_engine.so` and `libfr_std_cpp.so` contain flight-record obstacle-distance update and standardized distance-field names. Together these **suggest** app-side support for receiving/processing obstacle distance and displaying or recording it on some products. They do not establish which product, transport, field values, execution, raw LiDAR/depth exposure, or Neo 2 support. Native `radar` names may refer to other products and do not establish that Neo 2 has a radar sensor.

DJI's [Neo 2 specifications](https://www.dji.com/global/neo-2/specs) list omnidirectional monocular vision, downward infrared and forward LiDAR; its [FAQ](https://www.dji.com/global/neo-2/faq) tells users to watch DJI Fly warnings. A Neo 2-specific radar/distance display was not verified from DJI documentation or a connected aircraft. DJI describes Flight Data Center downloads of previously synced records in its [flight-record notice](https://viewpoints.dji.com/blog/download-your-data-before-it-gets-deleted), with US sync restrictions; the manifest also names flight-record/download activities. Neither establishes that Neo 2 obstacle distances are actually recorded, displayed in records, or available in an official export. No aircraft runtime or exported record was examined.
