#!/usr/bin/env python3
"""media-gen - turn a plain-language brief into images, a voiceover and a short video.

Keyless providers only:
  * images   - Pollinations (https://image.pollinations.ai)
  * voice    - edge-tts (Microsoft Edge neural voices)
  * video    - ffmpeg (bundled through imageio-ffmpeg)

Example:
  python media_gen.py --brief "three product photos of a ceramic mug on a wooden table" --out out/mug
  python media_gen.py --brief "an 8-second vertical video of coffee being poured" --out out/coffee --video

Outputs in --out:
  images/01.png ...         generated images
  voiceover.mp3             voiceover (if --voice)
  video.mp4                 assembled video (if --video)
  manifest.json             what was generated and how
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

USER_AGENT = "media-gen/1.0 (autonomous agent)"
POLLINATIONS = "https://image.pollinations.ai/prompt/{prompt}?width={w}&height={h}&nologo=true&seed={seed}"

ASPECTS = {
    "vertical": (720, 1280),
    "landscape": (1280, 720),
    "square": (1024, 1024),
}

WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def log(msg: str) -> None:
    print(msg, flush=True)


def parse_brief(brief: str) -> dict:
    """Very small brief parser: counts, duration and aspect."""
    text = brief.lower()
    count = 1
    for word, value in WORD_NUMBERS.items():
        if re.search(r"\b" + word + r"\b", text):
            count = value
            break
    match = re.search(r"\b(\d{1,3})\s*(images?|photos?|pictures?|pics?)\b", text)
    if match:
        count = int(match.group(1))
    duration = 6
    match = re.search(r"(\d{1,3})\s*(?:-|\s)?\s*second", text)
    if match:
        duration = int(match.group(1))
    aspect = "square"
    if "vertical" in text or "portrait" in text or "story" in text or "reel" in text:
        aspect = "vertical"
    elif "landscape" in text or "horizontal" in text or "wide" in text:
        aspect = "landscape"
    wants_video = any(k in text for k in ("video", "clip", "reel", "animation", "story"))
    wants_voice = any(k in text for k in ("voiceover", "voice", "narration", "audio"))
    return {"count": max(1, min(count, 10)), "duration": max(2, min(duration, 60)),
            "aspect": aspect, "video": wants_video, "voice": wants_voice}


def fetch(url: str, dest: str, attempts: int = 8, timeout: int = 180) -> str:
    """Download with curl: urllib's TLS gets reset on this network, curl works.

    Pollinations free tier allows one image per 45 seconds per IP and answers
    402 with a "Retry after Ns" hint; we honour that hint and retry.
    """
    last = None
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            ["curl.exe", "-sSL", "-A", USER_AGENT, "-m", str(timeout),
             "-o", dest, "-w", "%{http_code}", url],
            capture_output=True, text=True, timeout=timeout + 20,
        )
        code = (result.stdout or "").strip()
        size = os.path.getsize(dest) if os.path.exists(dest) else 0
        if code == "200" and size >= 1000:
            return dest
        body = ""
        try:
            with open(dest, "r", encoding="utf-8", errors="replace") as handle:
                body = handle.read(500)
        except OSError:
            body = ""
        match = re.search(r"Retry after (\d+)s", body)
        wait = int(match.group(1)) + 2 if match else 5
        last = "http %s: %s" % (code, body[:120])
        log("  attempt %d/%d http %s, waiting %ds" % (attempt, attempts, code, wait))
        time.sleep(wait)
    raise RuntimeError("could not download %s: %s" % (url, last))


def make_images(prompt: str, out_dir: str, count: int, aspect: str) -> list:
    width, height = ASPECTS[aspect]
    images = []
    os.makedirs(out_dir, exist_ok=True)
    for index in range(1, count + 1):
        variant = prompt if count == 1 else "%s (variation %d of %d)" % (prompt, index, count)
        url = POLLINATIONS.format(prompt=urllib.parse.quote(variant, safe=""),
                                  w=width, h=height, seed=index * 7919)
        dest = os.path.join(out_dir, "%02d.png" % index)
        log("image %d/%d ..." % (index, count))
        fetch(url, dest)
        images.append(dest)
    return images


def make_voiceover(text: str, dest: str) -> str:
    import edge_tts

    async def _run() -> None:
        communicate = edge_tts.Communicate(text, "en-US-AriaNeural")
        await communicate.save(dest)

    asyncio.run(_run())
    return dest


def ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def make_video(images: list, out_path: str, duration: int, voice_path: str | None) -> str:
    """Assemble a slideshow video; audio is the voiceover when present."""
    exe = ffmpeg()
    aspect = "720x1280" if images else "720x1280"
    per_image = max(1.0, duration / len(images))
    images = [os.path.abspath(image) for image in images]
    lines = []
    for image in images:
        lines.append("file '%s'" % image.replace("\\", "/"))
        lines.append("duration %.2f" % per_image)
    lines.append("file '%s'" % images[-1].replace("\\", "/"))
    concat_file = out_path + ".txt"
    with open(concat_file, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    cmd = [exe, "-y", "-f", "concat", "-safe", "0", "-i", concat_file]
    if voice_path:
        cmd += ["-i", voice_path]
    cmd += ["-fps_mode", "vfr", "-pix_fmt", "yuv420p", "-shortest", out_path]
    log("video: assembling %d image(s) into %s" % (len(images), out_path))
    result = subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(concat_file)
    if result.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError("ffmpeg failed: " + (result.stderr or "")[-600:])
    return out_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Brief -> images, voiceover, short video")
    parser.add_argument("--brief", required=True, help="plain-language brief")
    parser.add_argument("--out", required=True, help="output directory")
    parser.add_argument("--count", type=int, default=0, help="override image count")
    parser.add_argument("--duration", type=int, default=0, help="override video seconds")
    parser.add_argument("--aspect", default="", help="vertical|landscape|square")
    parser.add_argument("--video", action="store_true", help="force video assembly")
    parser.add_argument("--voice", action="store_true", help="force voiceover")
    parser.add_argument("--voice-text", default="", help="voiceover script (default: brief)")
    args = parser.parse_args(argv)

    plan = parse_brief(args.brief)
    count = args.count or plan["count"]
    duration = args.duration or plan["duration"]
    aspect = args.aspect or plan["aspect"]
    wants_video = args.video or plan["video"]
    wants_voice = args.voice or plan["voice"] or wants_video

    os.makedirs(args.out, exist_ok=True)
    manifest = {"brief": args.brief, "plan": {"count": count, "duration": duration,
                                              "aspect": aspect, "video": wants_video,
                                              "voice": wants_voice}}

    images = make_images(args.brief, os.path.join(args.out, "images"), count, aspect)
    manifest["images"] = images

    voice_path = None
    if wants_voice:
        voice_path = os.path.join(args.out, "voiceover.mp3")
        log("voiceover ...")
        try:
            make_voiceover(args.voice_text or args.brief, voice_path)
            manifest["voiceover"] = voice_path
        except Exception as exc:  # noqa: BLE001 - voice is optional
            log("  voiceover failed: %s" % str(exc)[:160])
            voice_path = None

    if wants_video:
        video_path = os.path.join(args.out, "video.mp4")
        make_video(images, video_path, duration, voice_path)
        manifest["video"] = video_path

    with open(os.path.join(args.out, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    log("done: %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
