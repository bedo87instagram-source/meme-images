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
        out_path.write_bytes(img_bytes)
        print(f"  wrote {out_path} ({len(img_bytes)} bytes)")
        made += 1
    print(f"done, {made} image(s) generated")


if __name__ == "__main__":
    main()
