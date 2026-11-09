#!/usr/bin/env python3
"""Extract chapter HTML from the NHK EPUB.

The EPUB exported from Pages has one XHTML file per top-level chapter and a
clean text layer. Its block conventions are:

  <h1>                                  chapter title (skipped, the page has one)
  <h3>                                  subsection heading
  <p class="p21">                       bold centered subsection heading
  <p class="p2">- ... -</p>             tagline
  <p class="p2">Ergänzende Maßnahmen</p> subsection heading
  <p class="p43 p44"><bdi>-</bdi> ...    list item
  <ol><li> ... </li></ol>               list
  <table> ... </table>                  data table

Text is clean, so no ligature/kerning repair is needed.
"""
import html
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from PIL import Image

NS = "{http://www.w3.org/1999/xhtml}"
BOLD_CLASSES = {"c17", "c2", "p6", "p8"}
ITALIC_CLASSES = {"c8"}
BULLETS = {"-", "\u2013", "\u2022"}


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def slugify(text: str) -> str:
    s = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def norm_title(text: str) -> str:
    """Normalize a TOC title for matching ('Husten / Heiserkeit' == 'Husten/Heiserkeit')."""
    return re.sub(r"\s+", " ", re.sub(r"\s*/\s*", "/", text)).strip().lower()


def _plain(el) -> str:
    # _inline adds a space for <br/>, which plain text extraction would lose.
    s = _inline(el)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s).replace("\u00a0", " ")
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def _inline(el) -> str:
    parts = []
    if el.text:
        parts.append(html.escape(el.text, quote=False))
    for child in el:
        tag = local(child.tag)
        if tag == "br":
            parts.append(" ")
        elif tag == "img":
            pass
        elif tag == "bdi":
            # A <bdi>-</bdi> is the bullet of a list item; drop it.
            if (child.text or "").strip() not in BULLETS:
                parts.append(_inline(child))
        elif tag in ("strong", "b"):
            parts.append("<strong>" + _inline(child) + "</strong>")
        elif tag in ("em", "i"):
            parts.append("<em>" + _inline(child) + "</em>")
        elif tag == "span":
            classes = set(child.get("class", "").split())
            inner = _inline(child)
            if classes & BOLD_CLASSES:
                parts.append("<strong>" + inner + "</strong>")
            elif classes & ITALIC_CLASSES:
                parts.append("<em>" + inner + "</em>")
            else:
                parts.append(inner)
        elif tag == "sup":
            parts.append("<sup>" + _inline(child) + "</sup>")
        elif tag == "sub":
            parts.append("<sub>" + _inline(child) + "</sub>")
        elif tag == "a":
            href = child.get("href", "")
            inner = _inline(child)
            if href.startswith(("http://", "https://")):
                parts.append(f'<a href="{html.escape(href)}">{inner}</a>')
            else:
                parts.append(inner)  # internal book links become plain text
        else:
            parts.append(_inline(child))
        if child.tail:
            parts.append(html.escape(child.tail, quote=False))
    return "".join(parts)


def _save_optimized(data: bytes, base: Path) -> Path:
    """Resize to max 1200px and save as WebP; fall back to the original bytes."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        if max(img.size) > 1200:
            img.thumbnail((1200, 1200), Image.LANCZOS)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        target = base.with_suffix(".webp")
        img.save(target, "WEBP", quality=88, method=6)
        return target
    except Exception:
        target = base.with_suffix(".png")
        target.write_bytes(data)
        return target


def _clean_inline(fragment: str) -> str:
    fragment = re.sub(r"</strong>\s*<strong>", "", fragment)
    fragment = re.sub(r"\s+", " ", fragment)
    return fragment.strip()


def _labelize(fragment: str, text: str) -> str:
    """Bold a leading ALL-CAPS label such as ALLGEMEIN: if it is not bold already."""
    if fragment.startswith("<strong>"):
        return fragment
    m = re.match(r"^([A-ZÄÖÜ][A-ZÄÖÜ\s/&.\-]{2,}):\s*", text)
    if not m:
        return fragment
    label = m.group(1).strip()
    if not fragment.startswith(label):
        return fragment
    rest = fragment[len(label):]
    rest = re.sub(r"^\s*:\s*", "", rest)
    return f"<strong>{html.escape(label)}:</strong> {rest}".strip()


def _is_tagline(text: str) -> bool:
    return len(text) > 4 and text[0] in BULLETS and text[-1] in BULLETS


def _looks_like_heading(text: str) -> bool:
    if not text or len(text) > 80 or len(text.split()) > 6:
        return False
    if text[0] in BULLETS or text[-1] in BULLETS:
        return False
    if text.endswith((".", ",", ";", ":", "?", "!")):
        return False
    if re.search(r"\d", text):
        return False
    return text[:1].isupper()


def _is_list_item(el, text: str) -> bool:
    classes = set(el.get("class", "").split())
    if classes & {"p43", "p44"}:
        return True
    if text.startswith(("- ", "\u2013 ", "\u2022 ")):
        return True
    for bdi in el.iter(f"{NS}bdi"):
        if (bdi.text or "").strip() in BULLETS:
            return True
    return False


def _iter_blocks(parent):
    for el in parent:
        tag = local(el.tag)
        if tag in ("div", "section"):
            yield from _iter_blocks(el)
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p", "ol", "ul", "table"):
            yield el


def parse_toc(epub_path: Path) -> list[dict]:
    """Return [{file, title, subs: [(anchor, title)]}] in book order."""
    with zipfile.ZipFile(epub_path) as z:
        source = z.read("OPS/toc.xhtml").decode("utf-8")
    chapters = []
    current = None
    for href, raw in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', source, re.S):
        title = html.unescape(re.sub(r"<[^>]+>", "", raw)).strip()
        file, _, fragment = href.partition("#")
        if fragment:
            if current is not None:
                current["subs"].append((fragment, title))
        else:
            current = {"file": file, "title": title, "subs": []}
            chapters.append(current)
    return chapters


def extract_chapter(
    epub_path: Path,
    chapter_file: str,
    sub_titles=(),
    image_dir: Path | None = None,
    image_prefix: str = "",
    image_slug: str = "",
) -> tuple[str, list[str]]:
    """Return (body_html, plain_blocks) for one chapter file.

    plain_blocks is used only for the meta description: it contains the title
    line first, then every block's plain text.
    """
    with zipfile.ZipFile(epub_path) as z:
        root = ET.fromstring(z.read("OPS/" + chapter_file))

    body = root.find(f".//{NS}div[@class='body s1']")
    if body is None:
        body = root.find(f".//{NS}body")

    subs = {norm_title(t) for t in sub_titles}
    out: list[str] = []
    plain: list[str] = []
    list_items: list[str] = []
    first_h1 = True
    first_tagline = True
    pending_caption = False

    def flush_list():
        nonlocal list_items
        if list_items:
            out.append(
                "<ul>\n"
                + "\n".join(f"        <li>{item}</li>" for item in list_items)
                + "\n      </ul>"
            )
            list_items = []

    def add_heading(text: str):
        flush_list()
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            out.append(f'<h2 id="{slugify(text)}">{html.escape(text)}</h2>')
            plain.append(text)

    for el in _iter_blocks(body):
        tag = local(el.tag)
        text = _plain(el)
        classes = set(el.get("class", "").split())

        if pending_caption:
            if tag == "p" and not text:
                continue
            is_caption = False
            if tag == "p" and text:
                is_caption = (
                    text.lower().startswith(
                        ("mit freundlicher genehmigung", "quelle", "foto", "grafik", "abb.", "bild:")
                    )
                    or (
                        "p2" in classes
                        and len(text) <= 120
                        and not _looks_like_heading(text)
                        and not _is_tagline(text)
                    )
                )
            if is_caption:
                out[-1] += f"<figcaption>{_clean_inline(_inline(el))}</figcaption></figure>"
                pending_caption = False
                continue
            out[-1] += "</figure>"
            pending_caption = False

        if tag == "h1":
            if first_h1:
                first_h1 = False
                continue
            add_heading(text)
            continue

        if tag in ("h2", "h3", "h4", "h5", "h6"):
            add_heading(text)
            continue

        if tag in ("ol", "ul"):
            items = []
            for li in el.findall(f".//{NS}li"):
                item = _clean_inline(_inline(li))
                item = re.sub(r"^\s*[-–•]\s*", "", item)
                item = _labelize(item, _plain(li))
                if item:
                    list_items.append(item)
                    plain.append(_plain(li))
            continue

        if tag == "table":
            flush_list()
            rows = []
            for tr in el.findall(f".//{NS}tr"):
                cells = tr.findall(f"{NS}td") + tr.findall(f"{NS}th")
                rendered = [_clean_inline(_inline(td)) for td in cells]
                if any(rendered):
                    rows.append("<tr>" + "".join(f"<td>{c}</td>" for c in rendered) + "</tr>")
                    plain.extend(_plain(td) for td in cells if _plain(td))
            if rows:
                out.append(
                    '<div class="table-wrap"><table>\n'
                    + "\n".join("        " + row for row in rows)
                    + "\n      </table></div>"
                )
            continue

        if tag != "p":
            continue

        imgs = el.findall(f".//{NS}img")
        if imgs:
            if image_dir is None:
                continue
            rendered_images = []
            for img in imgs:
                src = img.get("src", "")
                if not src:
                    continue
                try:
                    with zipfile.ZipFile(epub_path) as z:
                        data = z.read("OPS/" + src)
                except KeyError:
                    continue
                image_dir.mkdir(parents=True, exist_ok=True)
                base = image_dir / (f"{image_slug}__{Path(src).stem}" if image_slug else Path(src).stem)
                saved = _save_optimized(data, base)
                rendered_images.append(
                    f'<img src="{html.escape(image_prefix + saved.name)}" '
                    f'alt="Abbildung aus dem Buch" loading="lazy">'
                )
            if not rendered_images:
                continue

            meaningful = text.replace("\ufffc", "").strip()
            if meaningful:
                flush_list()
                fragment = _clean_inline(_inline(el))
                out.append(f"<p>{_labelize(fragment, text)}</p>")
                plain.append(text)

            flush_list()
            cls = "book-figure book-figure-row" if len(rendered_images) > 1 else "book-figure"
            out.append(f'<figure class="{cls}">' + "".join(rendered_images))
            pending_caption = True
            continue

        if not text:
            continue

        # Subsection headings: <h3> is handled above; p21/p6/p2 and TOC subs.
        if "p21" in classes and len(text) <= 80:
            add_heading(text)
            continue
        if ("p6" in classes or "p2" in classes) and _looks_like_heading(text):
            add_heading(text)
            continue
        if norm_title(text) in subs and len(text) <= 80:
            add_heading(text)
            continue

        if _is_tagline(text):
            flush_list()
            cleaned = text.strip("".join(BULLETS)).strip()
            cls = "lead" if first_tagline else "tagline"
            first_tagline = False
            out.append(f'<p class="{cls}">{html.escape(cleaned)}</p>')
            plain.append(text)
            continue

        if _is_list_item(el, text):
            item = _clean_inline(_inline(el))
            item = re.sub(r"^\s*[-–•]\s*", "", item)
            item = _labelize(item, text)
            if item:
                list_items.append(item)
                plain.append(text)
            continue

        flush_list()
        fragment = _clean_inline(_inline(el))
        if "p2" in classes:
            out.append(f'<p class="center">{fragment}</p>')
        else:
            out.append(f"<p>{_labelize(fragment, text)}</p>")
        plain.append(text)

    if pending_caption:
        out[-1] += "</figure>"

    flush_list()
    return "\n      ".join(out), plain
