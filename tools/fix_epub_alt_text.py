#!/usr/bin/env python3
"""Write the ALT_TEXT descriptions into the EPUB chapter XHTML files.

The EPUB is a ZIP of XHTML files. This script replaces the alt attribute of
every image in OPS/chapter-*.xhtml with the matching description from
build_chapters.ALT_TEXT, in image order. It preserves the EPUB container rules
(mimetype first, stored uncompressed) and is idempotent.

Usage:
  python3 tools/fix_epub_alt_text.py docs/docs/NHK2026.epub
"""
import html
import re
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_chapters import ALT_TEXT, DISPLAY  # noqa: E402
from epub_extract import parse_toc, slugify  # noqa: E402


def set_alt(tag: str, value: str) -> str:
    value = html.escape(value, quote=True)
    if re.search(r'\balt="[^"]*"', tag):
        return re.sub(r'\balt="[^"]*"', f'alt="{value}"', tag, count=1)
    if tag.rstrip().endswith("/>"):
        return tag.rstrip()[:-2] + f' alt="{value}"/>'
    return tag.rstrip()[:-1] + f' alt="{value}">'


def patch(path: Path) -> None:
    toc = {c["file"]: c["title"] for c in parse_toc(path)}
    with zipfile.ZipFile(path) as zin:
        items = [(info, zin.read(info.filename)) for info in zin.infolist()]

    out_items = []
    applied = 0
    for info, data in items:
        if re.fullmatch(r"OPS/chapter-\d+\.xhtml", info.filename):
            title = toc.get(info.filename.split("/")[-1], "")
            slug = slugify(DISPLAY.get(title, title))
            alts = ALT_TEXT.get(slug, [])
            if alts:
                text = data.decode("utf-8")
                counter = 0

                def repl(match):
                    nonlocal counter, applied
                    if counter < len(alts):
                        tag = set_alt(match.group(0), alts[counter])
                        counter += 1
                        applied += 1
                        return tag
                    counter += 1
                    return match.group(0)

                text = re.sub(r"<img\b[^>]*>", repl, text)
                data = text.encode("utf-8")
        out_items.append((info, data))

    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w") as zout:
        for info, data in out_items:
            if info.filename == "mimetype":
                zi = zipfile.ZipInfo("mimetype")
                zi.compress_type = zipfile.ZIP_STORED
                zout.writestr(zi, data)
            else:
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(zi, data)
    tmp.replace(path)
    print(f"patched {applied} image alt attributes in {path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    patch(Path(sys.argv[1]))
