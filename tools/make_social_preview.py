#!/usr/bin/env python3
"""Build the GitHub social preview card (1280x640) for the NHK book.

Uses the EPUB cover as the visual anchor and sets the title in Georgia, so the
text stays crisp and correctly spelled. Run from the repository root:

    .venv/bin/python tools/make_social_preview.py

Output: tools/social-preview.png
"""
import io
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
EPUB = ROOT / "docs" / "docs" / "NHK2026.epub"
OUTPUT = ROOT / "tools" / "social-preview.png"

WIDTH, HEIGHT = 1280, 640
MARGIN = 80

CREAM = (247, 243, 232)
GREEN = (31, 77, 45)
RED = (176, 58, 46)
GREY = (72, 70, 64)
PALE_GREEN = (223, 234, 214)

GEORGIA_BOLD = "/System/Library/Fonts/Supplemental/Georgia Bold.ttf"
GEORGIA = "/System/Library/Fonts/Supplemental/Georgia.ttf"
AVENIR = "/System/Library/Fonts/Avenir Next.ttc"


def font(path, size, index=0):
    return ImageFont.truetype(path, size, index=index)


def tracked_text(draw, xy, text, fnt, fill, tracking):
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=fnt, fill=fill)
        x += draw.textlength(char, font=fnt) + tracking


def wrap(draw, text, fnt, max_width):
    lines, line = [], ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if draw.textlength(candidate, font=fnt) <= max_width:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def load_cover():
    with zipfile.ZipFile(EPUB) as archive:
        data = archive.read("OPS/images/cover-image.png")
    return Image.open(io.BytesIO(data)).convert("RGB")


def main():
    canvas = Image.new("RGB", (WIDTH, HEIGHT), CREAM)
    draw = ImageDraw.Draw(canvas)

    # Soft green halo behind the book.
    halo = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse(
        (700, -40, 1360, 620), fill=(*PALE_GREEN, 120)
    )
    canvas = Image.alpha_composite(canvas.convert("RGBA"), halo).convert("RGB")
    draw = ImageDraw.Draw(canvas)

    # Book cover on the right, with a soft shadow.
    cover = load_cover()
    cover_height = 540
    cover_width = round(cover.width * cover_height / cover.height)
    cover = cover.resize((cover_width, cover_height), Image.LANCZOS)
    cover_x = WIDTH - MARGIN - cover_width
    cover_y = (HEIGHT - cover_height) // 2

    shadow = Image.new("RGBA", (cover_width + 60, cover_height + 60), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (20, 26, cover_width + 20, cover_height + 26), radius=12, fill=(0, 0, 0, 70)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas.paste(
        Image.new("RGB", shadow.size, CREAM),
        (cover_x - 30, cover_y - 30),
        shadow,
    )

    mask = Image.new("L", cover.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, cover_width - 1, cover_height - 1), radius=10, fill=255
    )
    canvas.paste(cover, (cover_x, cover_y), mask)
    draw.rounded_rectangle(
        (cover_x, cover_y, cover_x + cover_width, cover_y + cover_height),
        radius=10,
        outline=(255, 255, 255),
        width=1,
    )

    # Eyebrow.
    eyebrow_font = font(AVENIR, 17, index=2)
    tracked_text(
        draw,
        (MARGIN, 92),
        "KOSTENLOSE NEUAUFLAGE 2026",
        eyebrow_font,
        RED,
        tracking=2.4,
    )

    # Title.
    title_font = font(GEORGIA_BOLD, 64)
    subtitle_font = font(GEORGIA_BOLD, 44)
    draw.text((MARGIN, 124), "Naturheilkunde", font=title_font, fill=GREEN)
    draw.text((MARGIN, 206), "für den Hausgebrauch", font=subtitle_font, fill=GREEN)

    draw.rectangle((MARGIN, 284, MARGIN + 88, 288), fill=RED)

    # Description.
    body_font = font(AVENIR, 22, index=7)
    body = (
        "Über 300 Krankheitsbilder und Hausmittel – "
        "vollständig kostenlos als Web-Reader, PDF und eBook."
    )
    y = 316
    for line in wrap(draw, body, body_font, 640):
        draw.text((MARGIN, y), line, font=body_font, fill=GREY)
        y += 32

    # Footer.
    link_font = font(AVENIR, 20, index=2)
    credit_font = font(AVENIR, 17, index=7)
    draw.line((MARGIN, 492, 700, 492), fill=(214, 208, 192), width=1)
    draw.text((MARGIN, 512), "vogtpet.github.io/NHK", font=link_font, fill=GREEN)
    draw.text(
        (MARGIN, 546),
        "Willi Vogt · herausgegeben von Dr. Peter Vogt",
        font=credit_font,
        fill=GREY,
    )

    # Bottom accent.
    draw.rectangle((0, HEIGHT - 8, WIDTH, HEIGHT), fill=GREEN)

    canvas.save(OUTPUT, optimize=True)
    print(f"wrote {OUTPUT} ({OUTPUT.stat().st_size / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
