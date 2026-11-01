#!/usr/bin/env python3
"""Render the demo with Pillow cards and FFmpeg; never fetch source video."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
BG = "#F7F6F4"
INK = "#111820"
BLUE = "#2E6BF0"
MUTED = "#66717B"
LINE = "#DAD8D4"
SANS = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
BOLD = SANS.with_name("DejaVuSans-Bold.ttf")
MONO = SANS.with_name("DejaVuSansMono.ttf")


def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(MONO if mono else BOLD if bold else SANS), size)


def wrapped(draw: ImageDraw.ImageDraw, value: str, xy: tuple[int, int],
            width: int, size: int, fill: str = INK, bold: bool = False,
            gap: int = 12) -> int:
    x, y = xy
    face = font(size, bold)
    for paragraph in value.split("\n"):
        line = ""
        for word in paragraph.split():
            test = f"{line} {word}".strip()
            if line and draw.textlength(test, font=face) > width:
                draw.text((x, y), line, font=face, fill=fill)
                y += size + gap
                line = word
            else:
                line = test
        draw.text((x, y), line, font=face, fill=fill)
        y += size + gap
    return y


def base(scene: dict, index: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGB", (1920, 1080), BG)
    d = ImageDraw.Draw(im)
    d.rectangle((48, 34, 82, 68), fill=BLUE)
    d.rectangle((57, 43, 73, 59), outline="white", width=2)
    d.text((98, 31), "sentinel.", font=font(34, True), fill=INK)
    d.text((400, 43), "SPATIAL INTELLIGENCE / DEMO", font=font(17, mono=True), fill=MUTED)
    d.text((1610, 43), f"{index:02d} / 16", font=font(19, mono=True), fill=MUTED)
    d.line((48, 94, 1872, 94), fill=LINE, width=2)
    d.rectangle((48, 111, 57, 120), fill=BLUE)
    d.text((70, 106), scene["tag"], font=font(16, mono=True), fill=BLUE)
    d.line((48, 1004, 1872, 1004), fill=LINE, width=2)
    wrapped(d, scene["footer"], (48, 1020), 1800, 18, MUTED, gap=4)
    return im, d


def make_card(scene: dict, index: int, target: Path) -> None:
    im, d = base(scene, index)
    kind = scene["kind"]
    if kind == "media":
        d.rectangle((48, 146, 1408, 966), fill="#EFEEEB", outline=LINE, width=2)
        y = wrapped(d, scene["title"], (1460, 185), 390, 43, bold=True, gap=8)
        y = wrapped(d, scene["body"], (1460, y + 32), 390, 26, MUTED, gap=12)
        d.line((1460, max(753, y + 35), 1842, max(753, y + 35)), fill=BLUE, width=3)
        wrapped(d, scene["callout"], (1460, max(780, y + 62)), 390, 22, BLUE, gap=14)
    elif kind == "decisions":
        wrapped(d, scene["title"], (80, 185), 1750, 58, bold=True)
        for x, name, answer, conf, timing, policy, accent in [
            (80, "FULL BAY", "ok", "0.88", "1.44 s", "AUTO", BLUE),
            (1000, "EMPTY PICK FACE", "empty", "0.71", "0.64 s", "REVIEW", "#9B6626"),
        ]:
            d.rectangle((x, 342, x + 840, 822), fill="white", outline=LINE, width=2)
            d.rectangle((x, 342, x + 840, 349), fill=accent)
            d.text((x + 38, 385), name, font=font(21, mono=True), fill=MUTED)
            d.text((x + 38, 446), answer, font=font(82, True), fill=accent)
            d.text((x + 38, 575), f"{conf} confidence  /  {timing}", font=font(27), fill=INK)
            d.text((x + 38, 653), policy, font=font(27, mono=True), fill=accent)
            wrapped(d, "Real model call on a drawn bay image", (x + 38, 732), 760, 22, MUTED)
        d.text((80, 881), "Empty-bay severity: act_today probability 0.97 · separate 0.68 s call", font=font(28), fill=INK)
        d.text((80, 932), "Examples, not an accuracy benchmark. Low-stock ambiguity remains.", font=font(23), fill=MUTED)
    elif kind == "pipeline":
        wrapped(d, scene["title"], (80, 185), 1760, 54, bold=True)
        boxes = [
            ("01 / OBSERVE", "CCTV + drone video", "Local perception\nShort-lived tracks"),
            ("02 / LOCATE", "Shared twin", "Shelf / bay context\nMetric coordinates"),
            ("03 / JUDGE", "OpenAI Decisions", "Small blurred crops\nAuto / review / ignore"),
            ("04 / ACT", "Devin missions", "Plan inspections\nRaise staff tasks"),
        ]
        for n, (label, title, body) in enumerate(boxes):
            x = 80 + n * 450
            d.rectangle((x, 380, x + 420, 760), fill="white", outline=LINE, width=2)
            d.text((x + 25, 414), label, font=font(20, mono=True), fill=BLUE)
            wrapped(d, title, (x + 25, 485), 370, 32, bold=True)
            wrapped(d, body, (x + 25, 615), 370, 25, MUTED)
        wrapped(d, "AI manages the mission. Human / DJI controls the aircraft.", (80, 855), 1760, 39, BLUE)
        d.text((80, 929), "No AI or network calls inside the simulated local flight loop.", font=font(25), fill=MUTED)
    elif kind == "privacy":
        wrapped(d, scene["title"], (80, 185), 1740, 82, bold=True, gap=10)
        for n, (heading, body) in enumerate([
            ("LOCAL VIDEO", "Processing stays on the edge."),
            ("SMALL CROPS", "Only face-blurred evidence goes to the API."),
            ("NO IDENTITY", "No face recognition or cross-visit identity."),
        ]):
            y = 493 + n * 145
            d.rectangle((90, y + 9, 104, y + 23), fill=BLUE)
            d.text((130, y), heading, font=font(23, mono=True), fill=BLUE)
            d.text((490, y - 5), body, font=font(31), fill=INK)
    else:
        wrapped(d, scene["title"], (100, 236), 1710, 112, bold=True, gap=12)
        wrapped(d, scene["body"], (108, 580), 1650, 42, MUTED, gap=17)
        d.rectangle((108, 848, 182, 854), fill=BLUE)
        d.text((108, 893), "OBSERVE  /  UNDERSTAND  /  ACT", font=font(23, mono=True), fill=BLUE)
    im.save(target)


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def encode(scene: dict, card: Path, output: Path, inputs: Path) -> None:
    duration = str(scene["duration"])
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-threads", "2",
           "-loop", "1", "-framerate", "30", "-i", str(card)]
    filters = None
    if scene["kind"] == "media":
        asset = inputs / scene["asset"]
        if not asset.is_file():
            raise FileNotFoundError(f"Missing input: {asset}; see SOURCES.md")
        if asset.suffix.lower() in {".jpg", ".png"}:
            cmd += ["-loop", "1", "-framerate", "30"]
        elif asset.suffix.lower() == ".gif":
            cmd += ["-stream_loop", "-1"]
        if scene.get("start"):
            cmd += ["-ss", str(scene["start"])]
        cmd += ["-i", str(asset)]
        crop = f"crop={scene['crop']}," if "crop" in scene else ""
        filters = (f"[1:v]{crop}scale=1360:820:force_original_aspect_ratio=decrease,"
                   "setsar=1,fps=30[media];"
                   "[0:v][media]overlay=x=48+(1360-w)/2:y=146+(820-h)/2:shortest=1,"
                   "format=yuv420p[v]")
    if filters:
        cmd += ["-filter_complex_threads", "2", "-filter_complex", filters, "-map", "[v]"]
    cmd += ["-t", duration, "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "24",
            "-maxrate", "3500k", "-bufsize", "7000k", "-threads", "4", "-r", "30",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)]
    run(cmd)


def check_video(path: Path, minimum: float, maximum: float) -> dict:
    info = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_name,width,height:format=duration,size", "-of", "json", str(path)
    ]))
    video = next(s for s in info["streams"] if s["codec_name"] == "h264")
    assert (video["width"], video["height"]) == (1920, 1080), path
    assert minimum <= float(info["format"]["duration"]) <= maximum, path
    assert int(info["format"]["size"]) <= 60_000_000, path
    return {"file": path.name, **info["format"], **video}


def submission(inputs: Path, output: Path) -> None:
    source = inputs / "dashboard.mp4"
    if not source.is_file():
        raise FileNotFoundError(f"Missing input: {source}; see SOURCES.md")
    video = output / "sentinel-submission-88s.mp4"
    filters = (
        "crop=1400:899:0:88,scale=1920:1000:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:40:color=0xF7F6F4,setsar=1,"
        f"drawtext=fontfile={MONO}:fontsize=18:fontcolor=0x2E6BF0:x=182:y=10:"
        "text='RECORDED PRODUCT / SIMULATED DATA / READ-ONLY',"
        f"drawtext=fontfile={SANS}:fontsize=17:fontcolor=0x66717B:x=182:y=1050:"
        "text='Hosted replay. Ask answers are local summaries. Drone flight is simulated; no aircraft connected.'"
    )
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-t", "88", "-vf", filters, "-an", "-c:v", "libx264", "-preset", "fast",
         "-crf", "22", "-maxrate", "3500k", "-bufsize", "7000k", "-threads", "4",
         "-r", "30", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video)])
    report = check_video(video, 1, 90)
    (output / "submission-validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def cctv_submission(inputs: Path, output: Path) -> None:
    source = inputs / "cctv-assessed.mp4"
    captions = inputs / "cctv-captions.txt"
    for path in (source, captions):
        if not path.is_file():
            raise FileNotFoundError(f"Missing input: {path}; see SOURCES.md")
    lines = captions.read_text().splitlines()
    if not lines or len(lines) > 2 or any(len(line) > 140 for line in lines):
        raise ValueError("CCTV captions must have one or two lines, at most 140 characters each")
    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(source),
    ]))
    video = output / "sentinel-submission-cctv.mp4"
    caption_copy = output / "cctv-captions.txt"
    shutil.copyfile(captions, caption_copy)
    filters = (
        "scale=1920:1000:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:32:color=0xF7F6F4,setsar=1,"
        f"drawtext=fontfile={MONO}:fontsize=18:fontcolor=0x2E6BF0:x=80:y=7:"
        "text='SENTINEL / ACTi CCTV / RECORDED ASSESSMENT',"
        f"drawtext=fontfile={SANS}:fontsize=17:fontcolor=0x66717B:x=80:y=1038:"
        f"textfile='{caption_copy}':expansion=none:line_spacing=3"
    )
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-t", str(min(duration, 88.0)), "-vf", filters, "-an", "-c:v", "libx264",
         "-preset", "fast", "-crf", "22", "-maxrate", "3500k", "-bufsize", "7000k",
         "-threads", "4", "-r", "30", "-pix_fmt", "yuv420p", "-movflags",
         "+faststart", str(video)])
    report = check_video(video, 1, 90)
    (output / "cctv-validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, default=ROOT / "inputs")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--cards-only", action="store_true")
    mode.add_argument("--submission-only", action="store_true",
                      help="Export the earlier simulated-dashboard cut (no slides)")
    mode.add_argument("--cctv-only", action="store_true",
                      help="Export the actual CCTV assessment without unrelated example footage")
    args = parser.parse_args()
    scenes = json.loads((ROOT / "storyboard.json").read_text())
    assert 120 <= sum(s["duration"] for s in scenes) <= 150
    for executable in ("ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            raise RuntimeError(f"Install {executable} before rendering")
    for directory in (ROOT / "cards", ROOT / "output" / "segments"):
        directory.mkdir(parents=True, exist_ok=True)
    if args.cctv_only:
        cctv_submission(args.inputs, ROOT / "output")
        return
    if args.submission_only:
        submission(args.inputs, ROOT / "output")
        return
    for index, scene in enumerate(scenes, 1):
        card = ROOT / "cards" / f"{scene['id']}.png"
        make_card(scene, index, card)
        if not args.cards_only:
            print(f"Rendering {scene['id']} ({scene['duration']} s)", flush=True)
            encode(scene, card, ROOT / "output" / "segments" / f"{scene['id']}.mp4", args.inputs)
    if args.cards_only:
        return
    output = ROOT / "output"
    concat = output / "concat.txt"
    concat.write_text("".join(f"file 'segments/{s['id']}.mp4'\n" for s in scenes))
    master = output / "sentinel-demo-no-vo.mp4"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(master)])
    shutil.copyfile(master, output / "sentinel-demo.mp4")
    reports = [check_video(master, 120, 150)]
    for name, ids in [
        ("clip-twin-heatmap", ["02-overview", "04-top"]),
        ("clip-drone-patrol", ["11-patrol"]),
        ("clip-cctv-events", ["07-perception", "08-cctv"]),
    ]:
        playlist = output / f"{name}.txt"
        playlist.write_text("".join(f"file 'segments/{key}.mp4'\n" for key in ids))
        dest = output / f"{name}.mp4"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", str(playlist), "-c", "copy", "-movflags", "+faststart", str(dest)])
        reports.append(check_video(dest, 10, 20))
    (output / "validation.json").write_text(json.dumps(reports, indent=2) + "\n")
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
