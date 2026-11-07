#!/usr/bin/env python3
"""
Build per-chapter HTML pages for the NHK web edition.

Source of truth:
  - docs/NHK2026.pdf      -> chapter text (pages)
  - index.html            -> table of contents (titles + start pages)

Usage:
  python3 tools/build_chapters.py --pilot     # 10 pilot chapters
  python3 tools/build_chapters.py --all       # every top-level chapter
"""
import argparse
import html
import json
import logging
import re
import unicodedata
from pathlib import Path
from string import Template

logging.getLogger("pypdf").setLevel(logging.ERROR)
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
PDF_PATH = ROOT / "docs" / "NHK2026.pdf"
BASE_URL = "https://vogtpet.github.io/NHK"
SITE_NAME = "Naturheilkunde für den Hausgebrauch"
ISBN = "978-3-00-039171-2"
PUBLISHED = "2026-10-01"
LICENSE = "https://creativecommons.org/licenses/by/4.0/"

# Chapters built by --pilot (title -> optional display title override)
PILOT = [
    "Akne",
    "Arthrose",
    "Hypertonie",
    "Kopfschmerzen",
    "Husten / Heiserkeit",
    "Durchfall",
    "Sodbrennen",
    "Schlaflosigkeit",
    "Verstopfung",
    "Zecken",
]
DISPLAY = {
    "Hypertonie": "Hypertonie (Bluthochdruck)",
    "Husten / Heiserkeit": "Husten und Heiserkeit",
}

LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "ft", "ﬆ": "st"}
VOCAB: set[str] = set()


def build_vocab(reader) -> set[str]:
    """Every word that occurs in the book, used to validate rejoined fragments."""
    vocab = set()
    for page in reader.pages:
        for w in re.findall(r"[A-Za-zÄÖÜäöüß]{3,}", page.extract_text() or ""):
            vocab.add(w.lower())
    return vocab


# ---------------------------------------------------------------- text cleaning
def rejoin_tokens(text: str) -> str:
    """Undo kerning splits such as 'V erschlimmerung', 'H ä ufig', 'A f t e r'.

    Only merges when the first token is a single letter and the result really is a
    word that occurs elsewhere in the book — so 'Vitamin E einnehmen' stays intact.
    """
    tokens = text.split(" ")
    out, i = [], 0
    while i < len(tokens):
        if len(tokens[i]) == 1 and tokens[i].isalpha():
            for k in range(min(6, len(tokens) - i), 1, -1):
                head = tokens[i : i + k - 1]
                if not all(len(t) == 1 and t.isalpha() for t in head):
                    continue
                raw = "".join(tokens[i : i + k])
                core = re.sub(r"[^\wÄÖÜäöüß]", "", raw)
                if len(core) >= 4 and core.lower() in VOCAB:
                    out.append(raw)
                    i += k
                    break
            else:
                out.append(tokens[i])
                i += 1
            continue
        out.append(tokens[i])
        i += 1
    return " ".join(out)


def join_lines(lines) -> str:
    out = lines[0]
    for nxt in lines[1:]:
        if out.endswith("-") and nxt[:1].isupper():
            out = out[:-1] + "-" + nxt        # Hildegard-\nMedizin -> Hildegard-Medizin
        else:
            out = out + " " + nxt             # Bienen-\nbzw. -> Bienen- bzw.
    return out


def clean_text(s: str) -> str:
    s = s.replace("\u00ad", "").replace("\u00a0", " ")
    # a space directly before a ligature may or may not be an artefact ("häu ﬁgste"
    # vs "Häufig ﬁndet") - mark it, then decide using the book's own vocabulary
    s = re.sub(r"[ \t]+(?=[ﬀﬁﬂﬃﬄ])", "\x00", s)
    for k, v in LIGATURES.items():
        s = s.replace(k, v)

    def glue(m):
        joined = (m.group(1) + m.group(2)).lower()
        return m.group(1) + m.group(2) if joined in VOCAB else m.group(1) + " " + m.group(2)

    s = re.sub(r"([^\s\x00]+)\x00([^\s\x00]+)", glue, s)
    s = s.replace("\x00", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = rejoin_tokens(s)
    s = re.sub(r"([a-zäöüß])\.([A-ZÄÖÜ])", r"\1. \2", s)   # beruhigt.Deswegen
    s = re.sub(r"\s+([.,;:!?)])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r" {2,}", " ", s)
    return s.strip()


HEADING_BLACKLIST = ("hier ", "folgende", "diese ", "aber auch", "dazu ", "beispiel")


def is_heading(block: str) -> bool:
    if len(block) > 60 or block.endswith((".", ",", ";", ":")):
        return False
    if block.lower().startswith(HEADING_BLACKLIST):
        return False
    words = block.split()
    return 1 <= len(words) <= 6 and block[:1].isupper() and not block.startswith(("-", "•"))


LABEL_RE = re.compile(r"^([A-ZÄÖÜ][A-ZÄÖÜ\s/&.-]{2,}):\s*(.*)$")


def split_blocks(page_text):
    blocks, cur = [], []
    for line in page_text.split("\n"):
        s = line.strip()
        if not s:
            if cur:
                blocks.append(cur)
                cur = []
            continue
        if cur and (s.startswith(("-", "•")) or LABEL_RE.match(s)):
            blocks.append(cur)
            cur = [s]
        else:
            cur.append(s)
    if cur:
        blocks.append(cur)
    return blocks


def blocks_for(page_texts):
    out = []
    for text in page_texts:
        for lines in split_blocks(text):
            c = clean_text(join_lines(lines))
            if not c:
                continue
            # merge a paragraph that was split across a page boundary
            if (
                out
                and not re.search(r"[.!?:»“)-]$", out[-1])
                and not is_heading(out[-1])
                and not c.startswith(("-", "•"))
            ):
                out[-1] = out[-1] + " " + c
            else:
                out.append(c)
    return out


def render_body(blocks, title, subs):
    sub_map = {}
    for s in subs:
        sub_map.setdefault(clean_text(s).lower(), s)
    parts, list_open, lead_done = [], False, False
    for i, b in enumerate(blocks):
        low = b.lower()
        if i == 0 and slugify(b) == slugify(title):
            continue  # chapter title, already the <h1>
        if low in sub_map:
            if list_open:
                parts.append("</ul>")
                list_open = False
            display = sub_map[low]
            parts.append(f'<h2 id="{slugify(display)}">{html.escape(display)}</h2>')
            continue
        if b.startswith(("-", "•")):
            item = b.lstrip("-•").strip()
            if not item:
                continue
            if not lead_done and b.rstrip().endswith("-"):
                parts.append(f'<p class="lead">{html.escape(item.rstrip("- ").strip())}</p>')
                lead_done = True
                continue
            if not list_open:
                parts.append("<ul>")
                list_open = True
            parts.append(f"<li>{html.escape(item)}</li>")
            continue
        if list_open:
            parts.append("</ul>")
            list_open = False
        m = LABEL_RE.match(b)
        if m and m.group(2):
            parts.append(f"<p><strong>{html.escape(m.group(1))}:</strong> {html.escape(m.group(2))}</p>")
        elif m:
            parts.append(f'<h2 id="{slugify(m.group(1))}">{html.escape(m.group(1))}</h2>')
        elif is_heading(b):
            parts.append(f'<h2 id="{slugify(b)}">{html.escape(b)}</h2>')
        else:
            parts.append(f"<p>{html.escape(b)}</p>")
    if list_open:
        parts.append("</ul>")
    return "\n      ".join(parts)


def slugify(text: str) -> str:
    s = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


# ---------------------------------------------------------------- structure
def parse_toc():
    src = (ROOT / "index.html").read_text(encoding="utf-8")
    rows = re.findall(
        r'class="toc-link" href="docs/NHK2026\.pdf#page=(\d+)"[^>]*><span>(.*?)</span>', src
    )
    items = []
    for page, raw in rows:
        level = 1 if raw.startswith("&nbsp;") else 0
        title = html.unescape(re.sub(r"(&nbsp;)+", "", raw)).strip()
        items.append({"page": int(page), "title": title, "level": level})
    return items


def parse_chapters(toc, page_count):
    tops = [i for i, item in enumerate(toc) if item["level"] == 0]
    chapters = []
    for n, idx in enumerate(tops):
        nxt = tops[n + 1] if n + 1 < len(tops) else len(toc)
        end = toc[nxt]["page"] - 1 if nxt < len(toc) else page_count
        subs = [toc[j]["title"] for j in range(idx + 1, nxt) if toc[j]["level"] == 1]
        chapters.append(
            {
                "title": toc[idx]["title"],
                "slug": slugify(DISPLAY.get(toc[idx]["title"], toc[idx]["title"])),
                "start": toc[idx]["page"],
                "end": end,
                "subs": subs,
            }
        )
    return chapters


# ---------------------------------------------------------------- templates
TEMPLATE = Template("""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>$title – $site</title>
<meta name="description" content="$description">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="canonical" href="$canonical">
<meta name="author" content="Willi Vogt, Reinhild Vogt, Dr. Peter Vogt">
<meta property="og:type" content="article">
<meta property="og:site_name" content="$site">
<meta property="og:locale" content="de_DE">
<meta property="og:title" content="$title – $site">
<meta property="og:description" content="$description">
<meta property="og:url" content="$canonical">
<meta property="og:image" content="$base/assets/front.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" type="application/pdf" href="$base/docs/NHK2026.pdf">
<script type="application/ld+json">
$jsonld
</script>
<style>
:root { --ink:#22262b; --muted:#5b6672; --line:#e1e4e8; --brand:#2c3e50; --accent:#27ae60; }
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       color:var(--ink); line-height:1.65; background:#fff; }
a { color:#0366d6; }
.bar { background:var(--brand); color:#fff; display:flex; align-items:center; justify-content:space-between;
       gap:12px; padding:10px 20px; flex-wrap:wrap; }
.bar .brand { color:#fff; text-decoration:none; font-weight:600; font-size:15px; }
.bar .btn { background:var(--accent); color:#fff; text-decoration:none; padding:7px 12px; border-radius:4px;
            font-size:14px; font-weight:600; white-space:nowrap; }
.wrap { max-width:760px; margin:0 auto; padding:22px 20px 60px; }
.crumbs { font-size:13px; color:var(--muted); margin-bottom:14px; }
.crumbs a { color:var(--muted); }
h1 { font-size:30px; line-height:1.25; margin:6px 0 8px; }
.meta { color:var(--muted); font-size:14px; margin:0 0 22px; }
.lead { font-size:19px; color:#3b4650; border-left:3px solid var(--accent); padding-left:14px; margin:0 0 26px; }
h2 { font-size:20px; margin:30px 0 10px; padding-top:4px; }
p { margin:0 0 14px; }
ul { margin:0 0 16px; padding-left:22px; }
li { margin-bottom:8px; }
.disclaimer, .author { border:1px solid var(--line); border-radius:6px; padding:14px 16px; margin:30px 0 0;
                       font-size:14px; color:#3b4650; background:#fafbfc; }
.disclaimer strong, .author strong { color:var(--ink); }
.pager { display:flex; justify-content:space-between; gap:16px; margin:34px 0 0; padding-top:18px;
         border-top:1px solid var(--line); font-size:14px; }
.pager a { text-decoration:none; }
footer { border-top:1px solid var(--line); color:var(--muted); font-size:13px; padding:18px 20px;
         text-align:center; }
.skip { position:absolute; left:-9999px; }
.skip:focus { left:12px; top:12px; background:#fff; padding:8px; z-index:10; }
@media (max-width:600px){ h1{font-size:24px;} .bar{position:sticky;top:0;} }
</style>
</head>
<body>
<a class="skip" href="#inhalt">Zum Inhalt springen</a>
<header class="bar">
  <a class="brand" href="../">$site</a>
  <nav><a class="btn" href="$pdf_reader">Im Buch lesen (S. $page)</a></nav>
</header>
<div class="wrap">
  <nav class="crumbs" aria-label="Brotkrümelnavigation">
    <a href="../">Start</a> › <a href="../wissen/">Wissen A–Z</a> › <span>$title</span>
  </nav>
  <main id="inhalt">
    <h1>$title</h1>
    <p class="meta">Aus dem Buch <a href="../">$site</a> von Heilpraktiker Willi Vogt · Seite $page_range</p>
      $body
    <aside class="disclaimer">
      <strong>Wichtiger Hinweis:</strong> Diese Informationen dienen ausschließlich der allgemeinen Aufklärung
      und Selbsthilfe bei leichten Befindlichkeitsstörungen. Sie ersetzen in keinem Fall eine ärztliche
      Beratung, Diagnose oder Behandlung. Bei gesundheitlichen Beschwerden, chronischen Leiden oder
      anhaltenden Symptomen suchen Sie bitte qualifizierten ärztlichen Rat. Die Anwendung erfolgt auf
      eigene Verantwortung.
    </aside>
    <aside class="author">
      <strong>Willi Vogt</strong> (1939–2023) war Heilpraktiker und führte eine Naturheilpraxis in Boppard.
      Neuauflage 2026, bearbeitet von Reinhild Vogt und Dr. Peter Vogt. Lizenz:
      <a href="$license" rel="license">CC BY 4.0</a>.
    </aside>
    <nav class="pager">
      <span>$prev</span>
      <span>$next</span>
    </nav>
  </main>
</div>
<footer>
  <a href="../">Naturheilkunde für den Hausgebrauch</a> · <a href="$base/docs/NHK2026.pdf">PDF</a> ·
  <a href="$base/docs/NHK2026.epub">eBook</a> · <a href="https://github.com/vogtpet/NHK">Quellcode</a> ·
  ISBN $isbn
</footer>
</body>
</html>
""")


def build_jsonld(ch, url, description):
    data = {
        "@context": "https://schema.org",
        "@type": "Chapter",
        "name": DISPLAY.get(ch["title"], ch["title"]),
        "headline": DISPLAY.get(ch["title"], ch["title"]),
        "description": description,
        "url": url,
        "inLanguage": "de",
        "pageStart": ch["start"],
        "pageEnd": ch["end"],
        "datePublished": PUBLISHED,
        "license": LICENSE,
        "isPartOf": {
            "@type": "Book",
            "name": SITE_NAME,
            "isbn": ISBN,
            "url": BASE_URL + "/",
        },
        "author": {"@type": "Person", "name": "Willi Vogt", "jobTitle": "Heilpraktiker"},
        "contributor": [{"@type": "Person", "name": "Reinhild Vogt"}, {"@type": "Person", "name": "Dr. Peter Vogt"}],
        "publisher": {"@type": "Person", "name": "Dr. Peter Vogt"},
        "breadcrumb": {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Start", "item": BASE_URL + "/"},
                {"@type": "ListItem", "position": 2, "name": "Wissen A–Z", "item": BASE_URL + "/wissen/"},
                {"@type": "ListItem", "position": 3, "name": DISPLAY.get(ch["title"], ch["title"]), "item": url},
            ],
        },
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="build every top-level chapter")
    ap.add_argument("--pilot", action="store_true", help="build the 10 pilot chapters")
    ap.add_argument("--only", help="comma separated slugs to build")
    ap.add_argument("--batch", type=int, default=0, help="build the next N unbuilt chapters (1-based)")
    ap.add_argument("--size", type=int, default=30, help="chapters per batch (default 30)")
    args = ap.parse_args()

    reader = PdfReader(str(PDF_PATH))
    if reader.is_encrypted:
        reader.decrypt("")
    page_count = len(reader.pages)

    global VOCAB
    VOCAB = build_vocab(reader)
    print(f"  vocabulary: {len(VOCAB)} words")

    toc = parse_toc()
    chapters = parse_chapters(toc, page_count)
    on_disk = {c["slug"] for c in chapters if (ROOT / c["slug"] / "index.html").exists()}

    if args.all:
        selected = chapters
    elif args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        selected = [c for c in chapters if c["slug"] in wanted]
    elif args.batch:
        remaining = [c for c in chapters if c["slug"] not in on_disk]
        start = (args.batch - 1) * args.size
        selected = remaining[start : start + args.size]
        if not selected:
            print(f"  nothing left to build ({len(remaining)} unbuilt chapters)")
            return
    else:
        wanted = {slugify(DISPLAY.get(t, t)) for t in PILOT}
        selected = [c for c in chapters if c["slug"] in wanted]

    built = on_disk | {c["slug"] for c in selected}
    built_chapters = [c for c in chapters if c["slug"] in built]
    total_pages = 0

    def link_for(ch):
        if ch["slug"] in built:
            return f'<a href="../{ch["slug"]}/">{html.escape(DISPLAY.get(ch["title"], ch["title"]))}</a>'
        return f'<a href="../docs/NHK2026.pdf#page={ch["start"]}">{html.escape(ch["title"])}</a>'

    for ch in selected:
        pages = [reader.pages[p - 1].extract_text(extraction_mode="layout") or "" for p in range(ch["start"], ch["end"] + 1)]
        total_pages += len(pages)
        blocks = blocks_for(pages)
        body = render_body(blocks, ch["title"], ch["subs"])
        title = DISPLAY.get(ch["title"], ch["title"])
        url = f'{BASE_URL}/{ch["slug"]}/'

        tagline = next((b.lstrip("- ").strip() for b in blocks[1:3] if b.startswith("-")), None)
        if tagline:
            tagline = tagline.rstrip("-").strip()
        if not tagline or len(tagline) < 30:
            lab = next(
                (m for m in (LABEL_RE.match(b) for b in blocks[1:]) if m and m.group(2) and len(m.group(2)) > 60),
                None,
            )
            if lab:
                m = re.match(r"(.{40,}?[.!?])(?:\s|$)", lab.group(2))
                tagline = m.group(1) if m else lab.group(2)[:140]
            else:
                cand = next(
                    (b for b in blocks[1:] if len(b) > 80 and not b.startswith(("-", "•")) and not is_heading(b)),
                    "",
                )
                m = re.match(r"(.{40,}?[.!?])(?:\s|$)", cand)
                tagline = (m.group(1) if m else cand[:140]) or None
        if tagline:
            if len(tagline) > 95:
                tagline = tagline[:95].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
            core = f"{title}: {tagline}".rstrip("- ").strip()
            if not core.endswith((".", "!", "?", "…")):
                core += "."
        else:
            core = f"{title}: Hausmittel und naturheilkundliche Anwendungen."
        description = core + " Aus dem Buch von Heilpraktiker Willi Vogt, kostenlos online lesen."
        if len(description) > 158:
            description = description[:155].rsplit(" ", 1)[0] + "…"

        idx = chapters.index(ch)
        prev_ch = chapters[idx - 1] if idx > 0 else None
        next_ch = chapters[idx + 1] if idx + 1 < len(chapters) else None
        prev_html = "← " + link_for(prev_ch) if prev_ch else ""
        next_html = link_for(next_ch) + " →" if next_ch else ""

        out = TEMPLATE.substitute(
            title=html.escape(title),
            site=html.escape(SITE_NAME),
            description=html.escape(description),
            canonical=url,
            base=BASE_URL,
            pdf_reader=f'../docs/NHK2026.pdf#page={ch["start"]}',
            page=ch["start"],
            page_range=f'{ch["start"]}–{ch["end"]}',
            body=body,
            license=LICENSE,
            isbn=ISBN,
            prev=prev_html,
            next=next_html,
            jsonld=build_jsonld(ch, url, description),
        )
        target = ROOT / ch["slug"] / "index.html"
        target.parent.mkdir(exist_ok=True)
        target.write_text(out, encoding="utf-8")
        print(f'  {ch["slug"]:<28} S. {ch["start"]:>3}–{ch["end"]:<3} {len(body):>6} bytes')

    write_hub(selected, chapters, built)
    write_sitemap(built_chapters)
    print(f"\n{len(selected)} built this run, {len(built_chapters)} total, {total_pages} PDF pages extracted")


HUB = Template("""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wissen A–Z – $site</title>
<meta name="description" content="Alle Krankheitsbilder und Hausmittel aus „$site“ von Heilpraktiker Willi Vogt – kostenlos online lesen, von A bis Z.">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="canonical" href="$base/wissen/">
<meta property="og:type" content="website">
<meta property="og:site_name" content="$site">
<meta property="og:locale" content="de_DE">
<meta property="og:title" content="Wissen A–Z – $site">
<meta property="og:url" content="$base/wissen/">
<script type="application/ld+json">
$jsonld
</script>
<style>
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#22262b;line-height:1.6}
.bar{background:#2c3e50;padding:10px 20px}.bar a{color:#fff;text-decoration:none;font-weight:600}
.wrap{max-width:760px;margin:0 auto;padding:22px 20px 60px}
h1{font-size:28px;margin:6px 0 6px}
p.sub{color:#5b6672;margin:0 0 26px}
h2{font-size:16px;color:#5b6672;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #e1e4e8;padding-bottom:6px;margin:28px 0 10px}
ul{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:2px 18px}
li a{display:block;padding:6px 8px;border-radius:4px;text-decoration:none;color:#0366d6}
li a:hover{background:#f0f3f6}
li a.pdf{color:#5b6672}
footer{border-top:1px solid #e1e4e8;color:#5b6672;font-size:13px;padding:18px 20px;text-align:center}
</style>
</head>
<body>
<div class="bar"><a href="../">$site</a></div>
<div class="wrap">
  <h1>Wissen A–Z</h1>
  <p class="sub">Krankheitsbilder, Beschwerden und Hausmittel aus dem Buch „$site“ von Heilpraktiker
  Willi Vogt (1939–2023). Die Neuauflage 2026 steht vollständig kostenlos zur Verfügung – als
  Web-Reader, PDF und eBook.</p>
  <p class="sub">Kapitel mit eigener Seite sind hervorgehoben und enthalten den vollständigen Buchtext.
  Alle übrigen Einträge öffnen die entsprechende Seite im PDF. Neue Kapitel werden laufend ergänzt;
  Stand: November 2026.</p>
  $groups
</div>
<footer><a href="../">Zurück zum Web-Reader</a> · <a href="$base/docs/NHK2026.pdf">PDF</a> ·
<a href="$base/docs/NHK2026.epub">eBook</a> · Lizenz <a href="$license">CC BY 4.0</a></footer>
</body>
</html>
""")


def write_hub(selected, chapters, built):
    groups = {}
    for ch in chapters:
        if ch["title"] in ("Vorwort", "Einleitung", "Literaturverzeichnis", "Zeitschriften", "Bezugsquellen"):
            continue
        groups.setdefault(ch["title"][0].upper(), []).append(ch)
    out = []
    for letter in sorted(groups):
        items = []
        for ch in groups[letter]:
            label = html.escape(DISPLAY.get(ch["title"], ch["title"]))
            if ch["slug"] in built:
                items.append(f'<li><a href="../{ch["slug"]}/">{label}</a></li>')
            else:
                items.append(f'<li><a class="pdf" href="../docs/NHK2026.pdf#page={ch["start"]}">{label}</a></li>')
        out.append(f'<h2>{letter}</h2>\n<ul>\n  ' + "\n  ".join(items) + "\n</ul>")
    target = ROOT / "wissen" / "index.html"
    target.parent.mkdir(exist_ok=True)
    built_chapters = [c for c in chapters if c["slug"] in built]
    jsonld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": f"Wissen A–Z – {SITE_NAME}",
            "url": f"{BASE_URL}/wissen/",
            "inLanguage": "de",
            "description": f"Alle Krankheitsbilder und Hausmittel aus „{SITE_NAME}“ von Heilpraktiker Willi Vogt.",
            "isPartOf": {"@type": "Book", "name": SITE_NAME, "isbn": ISBN, "url": f"{BASE_URL}/"},
            "mainEntity": {
                "@type": "ItemList",
                "numberOfItems": len(built_chapters),
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": n,
                        "name": DISPLAY.get(c["title"], c["title"]),
                        "url": f'{BASE_URL}/{c["slug"]}/',
                    }
                    for n, c in enumerate(built_chapters, 1)
                ],
            },
        },
        ensure_ascii=False,
        indent=2,
    )
    target.write_text(
        HUB.substitute(
            site=html.escape(SITE_NAME),
            base=BASE_URL,
            license=LICENSE,
            groups="\n".join(out),
            jsonld=jsonld,
        ),
        encoding="utf-8",
    )
    print(f"  wissen/index.html  ({len(built)} linked chapters, {sum(len(v) for v in groups.values())} entries)")


def write_sitemap(built_chapters):
    urls = [(BASE_URL + "/", "2026-11-07"), (BASE_URL + "/wissen/", "2026-11-07")] + [
        (f'{BASE_URL}/{c["slug"]}/', "2026-11-07") for c in built_chapters
    ] + [(BASE_URL + "/docs/NHK2026.pdf", "2026-10-29")]
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, mod in urls:
        lines.append(f"  <url>\n    <loc>{loc}</loc>\n    <lastmod>{mod}</lastmod>\n  </url>")
    lines.append("</urlset>\n")
    (ROOT / "sitemap.xml").write_text("\n".join(lines), encoding="utf-8")
    print(f"  sitemap.xml  ({len(urls)} URLs)")


if __name__ == "__main__":
    main()
