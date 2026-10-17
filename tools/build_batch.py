#!/usr/bin/env python3
"""Build one content batch end to end from a spec file.

    python tools/build_batch.py specs/b02.json

For every entry in the spec:
  1. Generate a photoreal photo with Cloudflare Flux. File names are prefixed
     with the batch id (b02_001.jpg ...), so a photo from an older batch can
     never be picked up by accident. A photo that already exists for THIS batch
     is reused (so a re-run resumes), unless the entry has "force": true.
  2. Pillar formula/occasion -> a 7 s, 1080x1920 Reel with hook text (0-1.5 s)
     and payoff text (5.5-7 s). Text is auto-sized so it can never overflow.
     Pillar one_piece/capsule -> a tip card (slide 2 of a 3-slide carousel:
     photo, tip card, shared outro).
  3. Validate everything: files exist and have the right size/duration, the
     caption contains no hashtags (post.py adds them -- doubling happened once),
     no slide is an icon card, no duplicate titles.
Only if every entry passes are batches/<id>.json and batches/index.json
written. meme-poster then imports the batch automatically, append-only.

Spec format:
  {"batch_id": "b02", "entries": [
     {"pillar": "formula"|"occasion", "title": ..., "pieces": ..., "look": ...,
      "hook": [line1, line2], "payoff": ...},
     {"pillar": "one_piece"|"capsule", "title": ..., "pieces": ..., "look": ...,
      "tip_title": ..., "tips": [t1, t2, t3]} ]}

Env: CF_API_TOKEN, CF_ACCOUNT_ID. For local tests only: FAKE_PHOTO=<jpg path>.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from generate_photos import extend_to_4x5, generate_one  # noqa: E402

FONTS = ROOT / "fonts"
F_BOLD = str(FONTS / "Poppins-Bold.ttf")
F_REG = str(FONTS / "Poppins-Regular.ttf")
F_MED = str(FONTS / "Poppins-Medium.ttf")
F_SERIF = str(FONTS / "Lora-Variable.ttf")
HANDLE = "@dolphmd"
REEL_PILLARS = {"formula", "occasion"}
CAROUSEL_PILLARS = {"one_piece", "capsule"}
PROMPT_PREFIX = "Editorial fashion photograph of a single young woman standing alone, "
PROMPT_SUFFIX = (", plain neutral studio background, soft natural light, 50mm lens, full body, "
                 "photorealistic, high fashion editorial photography, sharp focus, one person only")


def log(msg):
    print(msg, flush=True)


def hx(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# --------------------------------------------------------------------------- photo
def make_photo(entry, out_path):
    fake = os.environ.get("FAKE_PHOTO")
    if fake:
        raw = Path(fake).read_bytes()
    else:
        prompt = PROMPT_PREFIX + entry["look"] + PROMPT_SUFFIX
        raw = generate_one(os.environ["CF_API_TOKEN"], os.environ["CF_ACCOUNT_ID"], prompt)
    out_path.write_bytes(extend_to_4x5(raw))


# --------------------------------------------------------------------------- tip card
def center_text(d, text, font, cx, y, fill, tracking=0):
    if tracking:
        widths = [d.textlength(ch, font=font) for ch in text]
        x = cx - (sum(widths) + tracking * (len(text) - 1)) / 2
        for ch, w in zip(text, widths):
            d.text((x, y), ch, font=font, fill=fill)
            x += w + tracking
    else:
        d.text((cx - d.textlength(text, font=font) / 2, y), text, font=font, fill=fill)


def wrap(d, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if d.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    lines.append(cur)
    return lines


def tip_card(out_path, title, tips):
    W, H = 1080, 1350
    img = Image.new("RGB", (W, H), hx("#F7F3EE"))
    d = ImageDraw.Draw(img)
    accent = "#B08D5F"
    center_text(d, "STYLING NOTES", ImageFont.truetype(F_MED, 30), W // 2, 110, hx(accent), tracking=6)
    f_title = ImageFont.truetype(F_SERIF, 56)
    ty = 220
    for line in wrap(d, title, f_title, 880)[:2]:
        center_text(d, line, f_title, W // 2, ty, hx("#2B2622"))
        ty += 68
    f_tip = ImageFont.truetype(F_REG, 30)
    rows = [wrap(d, t, f_tip, W - 320)[:3] for t in tips]
    row_h = [max(110, 40 * len(r) + 40) for r in rows]
    y = ty + 40 + max(0, (H - 160 - (ty + 40) - sum(row_h)) // 2)
    for i, (lines, h) in enumerate(zip(rows, row_h)):
        d.ellipse((150, y, 210, y + 60), fill=hx(accent))
        f_num = ImageFont.truetype(F_BOLD, 28)
        num = str(i + 1)
        d.text((180 - d.textlength(num, font=f_num) / 2, y + 15), num, font=f_num, fill=hx("#FFFFFF"))
        ly = y + 5
        for line in lines:
            d.text((250, ly), line, font=f_tip, fill=hx("#3A342C"))
            ly += 40
        y += h
    center_text(d, HANDLE, ImageFont.truetype(F_MED, 28), W // 2, H - 70, hx(accent), tracking=2)
    img.save(out_path, "JPEG", quality=93, optimize=True)


# --------------------------------------------------------------------------- reel
def fit_size(lines, start, minimum, max_w):
    for size in range(start, minimum - 1, -2):
        font = ImageFont.truetype(F_BOLD, size)
        if all(font.getlength(line) <= max_w for line in lines):
            return size
    return minimum


def make_reel(photo_path, hook, payoff, out_mp4):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        im = Image.open(photo_path).convert("RGB")
        fg = im.resize((1080, round(im.height * 1080 / im.width)))
        canvas = fg.resize((1080, 1920)).filter(ImageFilter.GaussianBlur(40))
        canvas.paste(fg, (0, (1920 - fg.height) // 2))
        vert = tmp / "vertical.jpg"
        canvas.save(vert, quality=92)
        hook_txt, payoff_txt = tmp / "hook.txt", tmp / "payoff.txt"
        hook_txt.write_text("\n".join(hook))
        payoff_txt.write_text(payoff)
        hs = fit_size(hook, 64, 40, 940)
        ps = fit_size([payoff], 48, 32, 940)
        vf = (
            f"drawtext=fontfile={F_BOLD}:textfile={hook_txt}:fontsize={hs}:fontcolor=white:"
            f"x=(w-text_w)/2:y=160:line_spacing=12:box=1:boxcolor=black@0.55:boxborderw=24:"
            f"enable='between(t,0,1.5)',"
            f"drawtext=fontfile={F_BOLD}:textfile={payoff_txt}:fontsize={ps}:fontcolor=white:"
            f"x=(w-text_w)/2:y=h-220:box=1:boxcolor=black@0.55:boxborderw=20:"
            f"enable='between(t,5.5,7)'"
        )
        cmd = ["ffmpeg", "-y", "-loop", "1", "-framerate", "30", "-t", "7", "-i", str(vert),
               "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
               "-r", "30", str(out_mp4)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {r.stderr[-1500:]}")


def probe(mp4):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
                        "-show_streams", str(mp4)], capture_output=True, text=True)
    d = json.loads(r.stdout)
    return float(d["format"]["duration"]), d["streams"][0]["width"], d["streams"][0]["height"]


# --------------------------------------------------------------------------- main
def check_spec(spec):
    problems = []
    if not spec.get("batch_id"):
        problems.append("spec has no batch_id")
    titles = set()
    for i, e in enumerate(spec.get("entries", []), start=1):
        p = e.get("pillar")
        need = ["title", "pieces", "look"] + (["hook", "payoff"] if p in REEL_PILLARS else ["tip_title", "tips"])
        if p not in REEL_PILLARS | CAROUSEL_PILLARS:
            problems.append(f"entry {i}: unknown pillar {p!r}")
        for k in need:
            if not e.get(k):
                problems.append(f"entry {i}: missing {k}")
        for k in ("title", "pieces"):
            if "#" in str(e.get(k, "")):
                problems.append(f"entry {i}: '#' in {k} -- hashtags are added by post.py")
        t = str(e.get("title", "")).strip().lower()
        if t in titles:
            problems.append(f"entry {i}: duplicate title {e.get('title')!r}")
        titles.add(t)
    return problems


def main():
    spec_path = Path(sys.argv[1])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    problems = check_spec(spec)
    if problems:
        for p in problems:
            log(f"SPEC ERROR: {p}")
        raise SystemExit(1)
    bid = spec["batch_id"]
    for sub in ("images/generated", "images/reels", "images/tip", "batches"):
        (ROOT / sub).mkdir(parents=True, exist_ok=True)

    out_entries, errors = [], []
    for i, e in enumerate(spec["entries"], start=1):
        name = f"{bid}_{i:03d}"
        photo = ROOT / "images/generated" / f"{name}.jpg"
        try:
            if e.get("force") or not photo.exists():
                log(f"[{name}] generating photo")
                make_photo(e, photo)
            else:
                log(f"[{name}] photo exists for this batch, reusing")
            with Image.open(photo) as im:
                if im.size != (1080, 1350):
                    raise RuntimeError(f"photo is {im.size}, expected (1080, 1350)")
            caption = f"{e['title']}\n{e['pieces']}"
            out = {"pillar": e["pillar"], "title": e["title"], "caption": caption, "batch": bid,
                   "tease_image": f"images/generated/{name}.jpg"}
            if e["pillar"] in REEL_PILLARS:
                mp4 = ROOT / "images/reels" / f"{name}.mp4"
                make_reel(photo, e["hook"], e["payoff"], mp4)
                dur, w, h = probe(mp4)
                if not (6.5 <= dur <= 7.5 and (w, h) == (1080, 1920)):
                    raise RuntimeError(f"reel check failed: {dur:.2f}s {w}x{h}")
                out["reel_video"] = f"images/reels/{name}.mp4"
                log(f"[{name}] reel ok ({dur:.2f}s {w}x{h}) -- {e['title']}")
            else:
                tip = ROOT / "images/tip" / f"{name}.jpg"
                tip_card(tip, e["tip_title"], e["tips"])
                out["image"] = f"images/tip/{name}.jpg"
                log(f"[{name}] carousel ok -- {e['title']}")
            out_entries.append(out)
        except Exception as exc:  # keep going so one bad entry shows all problems at once
            errors.append(f"[{name}] {exc}")
            log(f"[{name}] ERROR: {exc}")

    if errors:
        log(f"\n{len(errors)} entr(y/ies) failed -- batch NOT published. Re-run to resume:")
        for err in errors:
            log("  " + err)
        raise SystemExit(1)

    (ROOT / "batches" / f"{bid}.json").write_text(
        json.dumps({"batch_id": bid, "entries": out_entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    index_path = ROOT / "batches" / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"batches": []}
    if bid not in index["batches"]:
        index["batches"].append(bid)
    index_path.write_text(json.dumps(index, indent=2) + "\n")
    log(f"\nbatch {bid} published: {len(out_entries)} entries "
        f"({sum('reel_video' in x for x in out_entries)} reels, "
        f"{sum('image' in x for x in out_entries)} carousels)")


if __name__ == "__main__":
    main()
