# media-gen

Turn a plain-language brief into finished media files РІР‚вЂќ **images**, a **voiceover**, and a short **video** РІР‚вЂќ using keyless providers only.

```bash
python media_gen.py --brief "three product photos of a ceramic mug on a wooden table" --out out/mug
python media_gen.py --brief "an 8-second vertical video of coffee being poured" --out out/coffee
```

## What it produces

| Output | File | Provider |
|---|---|---|
| Images (1РІР‚вЂњ10) | `images/01.png РІР‚В¦` | [Pollinations](https://image.pollinations.ai) РІР‚вЂќ free tier, keyless |
| Voiceover | `voiceover.mp3` | [edge-tts](https://github.com/rany2/edge-tts) РІР‚вЂќ Microsoft Edge neural voices, keyless |
| Short video | `video.mp4` | ffmpeg (bundled via `imageio-ffmpeg`) |
| Manifest | `manifest.json` | what was generated and how |

The brief is parsed for the number of assets, the video duration and the aspect
ratio ("vertical", "landscape", "square"), and the script decides whether a
video and a voiceover are expected. Every step can also be forced with
`--count`, `--duration`, `--aspect`, `--video`, `--voice`, `--voice-text`.

## Install

```bash
python -m pip install edge-tts imageio-ffmpeg
```

Python 3.10+; `curl` must be available (used for downloads because some
networks reset Python's TLS client).

## Example output

```
$ python media_gen.py --brief "an 8-second vertical video of coffee being poured" --out out/coffee
image 1/2 ...
image 2/2 ...
  attempt 1/8 http 402, waiting 43s      # free-tier rate limit, handled
voiceover ...
video: assembling 2 image(s) into out/coffee/video.mp4
done: out/coffee
```

## Limitations (honest)

- **Pollinations free tier allows one image per 45 seconds per IP.** The script
  waits for the advertised retry window, so a 3-image job takes ~1.5РІР‚вЂњ2.5
  minutes. A paid "pollen key" removes the limit but is not required.
- **edge-tts needs outbound access to Microsoft's speech endpoint.** If it is
  blocked, the script logs the failure and still produces images (and a silent
  video if requested).
- **The video is a slideshow-style assembly** of generated stills with the
  voiceover track. It is not a generative video model.
- Generation is best-effort: providers can rate-limit or change. The script
  retries and reports what actually happened in `manifest.json`.

## Licence

MIT.

## clip_gen.py - short vertical clips

`ash
python clip_gen.py --input video.mp4 --out clips/ --clips 3 --max-duration 20 --vertical --title "Launch day"
`

Detects scene changes with ffmpeg, snaps clip boundaries to them, centre-crops to
9:16 (1080x1920), optionally burns in a title, and writes clip_01.mp4 вЂ¦ plus
manifest.json with the exact cut points.
## Premium image provider: Venice (x402, no account)

`ash
python media_gen.py --brief "a ceramic mug on a wooden table" --out out/mug --provider venice
`

Uses the Venice API through x402: the wallet pays per request in USDC on Base, with
no account, API key or KYC. lux-2-pro costs about \.03 per image. The script
falls back to Pollinations automatically when Venice is not configured or the
balance is empty (--provider auto is the default).