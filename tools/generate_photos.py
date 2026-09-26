#!/usr/bin/env python3
"""Generate photoreal fashion images via Cloudflare Workers AI (Flux schnell).

Reads a JSON job list (each: {"name": "...", "prompt": "..."}), calls the
Workers AI REST API for each, decodes the returned base64 JPEG, and saves it
to images/generated/<name>.jpg.

Env vars required: CF_API_TOKEN, CF_ACCOUNT_ID
Usage: python generate_photos.py jobs.json
"""
import base64
import json
import os
import sys
import time
from pathlib import Path

import requests
from io import BytesIO
from PIL import Image, ImageFilter

MODEL = "@cf/black-forest-labs/flux-1-schnell"
OUT_DIR = Path("images/generated")


def generate_one(token, account_id, prompt, seed=None, steps=8, retries=3):
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{MODEL}"
    # Note: this model's schema rejects a top-level "seed" property (HTTP 400,
    # "Additional or unevaluated properties '/seed' at '/' not allowed").
    # Confirmed via a real failed run's log. steps is accepted (max 8).
    body = {"prompt": prompt, "steps": steps}
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
                timeout=90,
            )
        except requests.RequestException as exc:
            last_err = str(exc)
            time.sleep(5)
            continue
        if r.status_code == 200:
            data = r.json()
            if data.get("success") and data.get("result", {}).get("image"):
                return base64.b64decode(data["result"]["image"])
            last_err = f"unexpected response body: {json.dumps(data)[:300]}"
        else:
            last_err = f"HTTP {r.status_code}: {r.text[:300]}"
        time.sleep(5)
    raise RuntimeError(f"generation failed after {retries} attempts: {last_err}")


def extend_to_4x5(img_bytes, target=(1080, 1350)):
    """Flux returns a 1024x1024 square. Extend it to Instagram's 4:5 portrait
    ratio by padding top/bottom with a blurred, darkened stretch of the same
    image, so the studio backdrop continues naturally instead of being
    cropped (which risks cutting off the subject's head or feet)."""
    tw, th = target
    im = Image.open(BytesIO(img_bytes)).convert("RGB")
    scale = tw / im.width
    fg = im.resize((tw, round(im.height * scale)), Image.LANCZOS)
    bg = fg.resize((tw, th), Image.LANCZOS).filter(ImageFilter.GaussianBlur(40))
    canvas = bg.copy()
    y = (th - fg.height) // 2
    canvas.paste(fg, (0, y))
    out = BytesIO()
    canvas.save(out, "JPEG", quality=92)
    return out.getvalue()

def main():
    token = os.environ["CF_API_TOKEN"]
    account_id = os.environ["CF_ACCOUNT_ID"]
    jobs = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    made = 0
    for job in jobs:
        out_path = OUT_DIR / f"{job['name']}.jpg"
        if out_path.exists() and not job.get("force"):
            print(f"skip (exists): {out_path}")
            continue
        print(f"generating: {job['name']} -> {job['prompt'][:80]}...")
        img_bytes = generate_one(token, account_id, job["prompt"])
        img_bytes = extend_to_4x5(img_bytes)
        out_path.write_bytes(img_bytes)
        print(f"  wrote {out_path} ({len(img_bytes)} bytes)")
        made += 1
    print(f"done, {made} image(s) generated")


if __name__ == "__main__":
    main()


