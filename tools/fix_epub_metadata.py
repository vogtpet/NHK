#!/usr/bin/env python3
"""Add publisher, contributors and description to a Pages-exported EPUB.

Pages 14 writes dc:title and dc:creator from the EPUB export options, but it
ignores the publisher option and does not add contributors. This script patches
the OPF metadata in place, preserving the EPUB container rules (mimetype first,
stored uncompressed).

Usage:
  python3 tools/fix_epub_metadata.py docs/NHK2026.epub
"""
import re
import sys
import zipfile
from pathlib import Path

PUBLISHER = "Dr. Peter Vogt"
CONTRIBUTORS = [
    ("contrib-reinhild", "Reinhild Vogt", "ctb"),  # contributor
    ("contrib-peter", "Dr. Peter Vogt", "edt"),    # editor / Herausgeber
]
DESCRIPTION = (
    "Naturheilkunde für den Hausgebrauch – Neuauflage 2026. "
    "Herausgegeben von Dr. Peter Vogt. Kostenlos unter https://vogtpet.github.io/NHK/"
)
MODIFIED = "2026-11-08T00:00:00Z"


def build_addition() -> str:
    parts = [f"<dc:publisher>{PUBLISHER}</dc:publisher>"]
    for cid, name, role in CONTRIBUTORS:
        parts.append(f'<dc:contributor id="{cid}">{name}</dc:contributor>')
        parts.append(
            f'<meta refines="#{cid}" property="role" scheme="marc:relators">{role}</meta>'
        )
    parts.append(f"<dc:description>{DESCRIPTION}</dc:description>")
    return "".join(parts)


def patch(path: Path) -> None:
    with zipfile.ZipFile(path) as zin:
        items = [(info, zin.read(info.filename)) for info in zin.infolist()]

    names = [info.filename for info, _ in items]
    if names[0] != "mimetype":
        raise SystemExit("EPUB error: mimetype is not the first entry")

    opf_name = next(n for n in names if n.endswith(".opf"))
    opf = next(data for info, data in items if info.filename == opf_name).decode("utf-8")

    # Remove values this script owns, so re-running is idempotent.
    opf = re.sub(r"<dc:publisher>.*?</dc:publisher>", "", opf, flags=re.S)
    opf = re.sub(r"<dc:description>.*?</dc:description>", "", opf, flags=re.S)
    for cid, _, _ in CONTRIBUTORS:
        opf = re.sub(
            rf'<dc:contributor id="{re.escape(cid)}">.*?</dc:contributor>', "", opf, flags=re.S
        )
        opf = re.sub(
            rf'<meta refines="#{re.escape(cid)}"[^>]*/>', "", opf
        )
    opf = re.sub(
        r'<meta property="dcterms:modified">.*?</meta>',
        f'<meta property="dcterms:modified">{MODIFIED}</meta>',
        opf,
        flags=re.S,
    )

    if "</metadata>" not in opf:
        raise SystemExit("EPUB error: no </metadata> in OPF")
    opf = opf.replace("</metadata>", build_addition() + "</metadata>", 1)

    tmp = path.with_suffix(".tmp")
    with zipfile.ZipFile(tmp, "w") as zout:
        for info, data in items:
            if info.filename == "mimetype":
                zi = zipfile.ZipInfo("mimetype")
                zi.compress_type = zipfile.ZIP_STORED
                zout.writestr(zi, data)
            elif info.filename == opf_name:
                zi = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                zi.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(zi, opf.encode("utf-8"))
            else:
                zout.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    tmp.replace(path)
    print(f"patched {path}: publisher + {len(CONTRIBUTORS)} contributors + description")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    patch(Path(sys.argv[1]))
