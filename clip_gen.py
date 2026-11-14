#!/usr/bin/env python3
"""clip-gen - cut a video into short vertical clips using ffmpeg only.

Approach:
  1. Detect scene changes (select='gt(scene,THRESHOLD)') and read their timestamps.
  2. Split the timeline into segments of at most --max-duration seconds,
     snapping each segment end to the nearest scene change when one is close.
  3. Export each segment as an independent clip, optionally cropped to 9:16,
     optionally with a burned-in title.

Example:
  python clip_gen.py --input video.mp4 --out clips/ --clips 3 --max-duration 20
  python clip_gen.py --input video.mp4 --out clips/ --vertical --title "Launch day"

Outputs: clips/clip_01.mp4 ... plus clips/manifest.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe_duration(path: str) -> float:
    exe = ffmpeg()
    result = subprocess.run([exe, "-hide_banner", "-i", path], capture_output=True, text=True)
    match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr or "")
    if not match:
        return 0.0
    hours, minutes, seconds = int(match.group(1)), int(match.group(2)), float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def scene_cuts(path: str, threshold: float = 0.3) -> list:
    exe = ffmpeg()
    result = subprocess.run(
        [exe, "-hide_banner", "-i", path, "-filter:v",
         "select='gt(scene,%.2f)',showinfo" % threshold, "-f", "null", "-"],
        capture_output=True, text=True,
    )
    times = [float(t) for t in re.findall(r"pts_time:([0-9.]+)", result.stderr or "")]
    return sorted(set(round(t, 2) for t in times))


def snap(end: float, cuts: list, window: float = 3.0) -> float:
    """Move a segment end to the nearest scene cut within `window` seconds."""
    best = end
    best_delta = window
    for cut in cuts:
        delta = abs(cut - end)
        if delta < best_delta:
            best, best_delta = cut, delta
    return max(1.0, best)


def segment_bounds(duration: float, count: int, max_duration: float, cuts: list) -> list:
    if count <= 0:
        count = max(1, int(round(duration / max_duration)))
    length = duration / count
    bounds = []
    start = 0.0
    for index in range(count):
        end = duration if index == count - 1 else snap(start + length, cuts)
        end = min(end, start + max_duration) if index < count - 1 else end
        if end - start >= 1.0:
            bounds.append((round(start, 2), round(end, 2)))
        start = end
    return bounds


def export_clip(src: str, dest: str, start: float, end: float, vertical: bool,
                title: str | None) -> str:
    exe = ffmpeg()
    filters = []
    if vertical:
        # centre-crop to 9:16 then scale to 1080x1920
        filters.append("crop=ih*9/16:ih:(iw-ih*9/16)/2:0")
        filters.append("scale=1080:1920:force_original_aspect_ratio=increase")
        filters.append("crop=1080:1920")
    if title:
        safe = title.replace("'", "").replace(":", " ")[:60]
        filters.append("drawtext=text='%s':x=(w-text_w)/2:y=h*0.08:fontsize=48:"
                       "fontcolor=white:box=1:boxcolor=black@0.35:boxborderw=12" % safe)
    cmd = [exe, "-y", "-ss", "%.2f" % start, "-to", "%.2f" % end, "-i", src]
    if filters:
        cmd += ["-vf", ",".join(filters)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", dest]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + (result.stderr or "")[-500:])
    return dest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Cut a video into short clips")
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--clips", type=int, default=3)
    parser.add_argument("--max-duration", type=float, default=25.0)
    parser.add_argument("--vertical", action="store_true")
    parser.add_argument("--title", default="")
    parser.add_argument("--scene-threshold", type=float, default=0.3)
    args = parser.parse_args(argv)

    if not os.path.exists(args.input):
        print("clip-gen: input not found: %s" % args.input, file=sys.stderr)
        return 1
    os.makedirs(args.out, exist_ok=True)
    duration = probe_duration(args.input)
    if duration <= 0:
        print("clip-gen: cannot read duration", file=sys.stderr)
        return 1
    cuts = scene_cuts(args.input, args.scene_threshold)
    print("duration %.1fs, scene cuts: %d" % (duration, len(cuts)))
    bounds = segment_bounds(duration, args.clips, args.max_duration, cuts)
    made = []
    for index, (start, end) in enumerate(bounds, start=1):
        dest = os.path.join(args.out, "clip_%02d.mp4" % index)
        print("clip %d: %.1fs -> %.1fs" % (index, start, end))
        export_clip(args.input, dest, start, end, args.vertical, args.title or None)
        made.append({"file": dest, "start": start, "end": end})
    manifest = {"input": args.input, "duration": duration, "scene_cuts": cuts,
                "vertical": args.vertical, "clips": made}
    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    print("done: %d clips in %s" % (len(made), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
