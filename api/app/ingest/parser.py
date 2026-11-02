"""PDF and TXT -> sections (SPEC section 3 step 2).

Section text has its whitespace collapsed to single spaces, because PDF line breaks would
otherwise defeat exact quote matching. Fact offsets refer to this collapsed text.
"""
import bisect
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.ingest.prompts import SKIPPED_HEADINGS

MAX_HEADING_CHARS = 120
MAX_TXT_HEADING_CHARS = 80
HEADING_SIZE_RATIO = 1.15
REPEATED_LINE_PAGES = 3
_NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)[.)]?\s+\S")
_FOOTER = re.compile(r"\d+\s*/\s*\d+")


class ParseError(ValueError):
    pass


@dataclass
class ParsedSection:
    heading: str
    level: int
    position: int
    page_start: int
    page_end: int
    text: str
    parent_position: int | None = None
    # (offset in text, 1-based page), ascending.
    page_map: list[tuple[int, int]] = field(default_factory=list)

    def page_at(self, offset: int) -> int:
        if not self.page_map:
            return self.page_start
        i = bisect.bisect_right([o for o, _ in self.page_map], offset) - 1
        return self.page_map[max(i, 0)][1]


@dataclass
class _Boundary:
    page: int  # 0-based
    heading_start: int
    body_start: int
    level: int
    heading: str


def normalize(text: str) -> str:
    return " ".join(text.replace("\x00", " ").split())


def _is_footer(line: str) -> bool:
    return bool(_FOOTER.fullmatch(line))


def _is_skipped_heading(line: str) -> bool:
    wanted = {h.casefold() for h in SKIPPED_HEADINGS}
    return line.replace("’", "'").casefold() in wanted


def _line_style(spans: list[dict]) -> tuple[float, bool]:
    size = max(round(s["size"], 1) for s in spans)
    bold = all(s["flags"] & 16 or "bold" in s["font"].lower() for s in spans)
    return size, bold


def _visible_lines(doc: pymupdf.Document) -> list[tuple[int, int, float, bool, str]]:
    """(page, block, size, bold, text) without footers or skipped blocks.

    A skipped block ends at the next bold line at least as large as its heading, even on a later page.
    """
    lines = []
    skip_size: float | None = None
    for page_no, page in enumerate(doc):
        for block_no, block in enumerate(page.get_text("dict")["blocks"]):
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = normalize("".join(s["text"] for s in line["spans"]))
                if _is_footer(text):
                    continue
                size, bold = _line_style(spans)
                if _is_skipped_heading(text):
                    skip_size = size
                    continue
                if skip_size is not None:
                    if not (bold and size >= skip_size):
                        continue
                    skip_size = None
                lines.append((page_no, block_no, size, bold, text))
    return lines


def _find_heading(title: str, page_text: str, start: int) -> re.Match | None:
    return re.compile(re.escape(title), re.IGNORECASE).search(page_text, start)


def _boundaries(entries: list[tuple[int, int, str]], pages: list[str]) -> list[_Boundary]:
    """entries: (level, 0-based page, title) in reading order."""
    out: list[_Boundary] = []
    page, cursor = -1, 0
    for level, entry_page, title in entries:
        if entry_page != page:
            page, cursor = entry_page, 0
        match = _find_heading(title, pages[page], cursor)
        if match:
            start, cursor = match.start(), match.end()
        else:
            # A heading absent from the page text starts the section where we stand.
            start = cursor
        out.append(_Boundary(page, start, cursor, level, title))
    return out


def _assemble(pages: list[str], boundaries: list[_Boundary]) -> list[ParsedSection]:
    if boundaries:
        first = boundaries[0]
        before = pages[: first.page] + [pages[first.page][: first.heading_start]]
        if any(p.strip() for p in before):
            boundaries = [_Boundary(0, 0, 0, 1, "Introduction")] + boundaries

    sections: list[ParsedSection] = []
    for position, b in enumerate(boundaries):
        if position + 1 < len(boundaries):
            end_page, end_char = boundaries[position + 1].page, boundaries[position + 1].heading_start
        else:
            end_page, end_char = len(pages) - 1, len(pages[-1])

        text, page_map = "", []
        for p in range(b.page, end_page + 1):
            start = b.body_start if p == b.page else 0
            stop = end_char if p == end_page else len(pages[p])
            piece = pages[p][start:stop].strip()
            if not piece:
                continue
            if text:
                text += " "
            page_map.append((len(text), p + 1))
            text += piece

        sections.append(
            ParsedSection(
                heading=b.heading,
                level=b.level,
                position=position,
                page_start=b.page + 1,
                page_end=page_map[-1][1] if page_map else b.page + 1,
                text=text,
                page_map=page_map,
            )
        )
    _link_parents(sections)
    return sections


def _link_parents(sections: list[ParsedSection]) -> None:
    stack: list[ParsedSection] = []
    for section in sections:
        while stack and stack[-1].level >= section.level:
            stack.pop()
        section.parent_position = stack[-1].position if stack else None
        stack.append(section)


def _toc_entries(doc: pymupdf.Document, page_count: int) -> list[tuple[int, int, str]]:
    entries = []
    for level, title, page, *_ in doc.get_toc():
        title = normalize(title)
        # A TOC entry can have no destination, or point past the end.
        if title and 1 <= page <= page_count and not _is_skipped_heading(title):
            entries.append((level, page - 1, title))
    return entries


def _font_entries(lines: list[tuple[int, int, float, bool, str]]) -> list[tuple[int, int, str]]:
    sizes: Counter[float] = Counter()
    for _, _, size, _, text in lines:
        sizes[size] += len(text)
    if not sizes:
        return []

    body = sizes.most_common(1)[0][0]
    candidates: list[tuple[int, int, float, str]] = []
    for page_no, block_no, size, bold, text in lines:
        looks_like_heading = (
            len(text) <= MAX_HEADING_CHARS
            and any(c.isalpha() for c in text)
            and not text.endswith((".", ",", ";", ":"))
        )
        if not looks_like_heading or not (size >= body * HEADING_SIZE_RATIO or (bold and size >= body)):
            continue
        previous = candidates[-1] if candidates else None
        if previous and previous[:3] == (page_no, block_no, size):
            candidates[-1] = (page_no, block_no, size, f"{previous[3]} {text}")  # a wrapped heading
        else:
            candidates.append((page_no, block_no, size, text))

    # A line repeating across pages is a running header, not a heading.
    seen = Counter(text.lower() for *_, text in candidates)
    candidates = [c for c in candidates if seen[c[3].lower()] < REPEATED_LINE_PAGES]
    levels = {size: i + 1 for i, size in enumerate(sorted({c[2] for c in candidates}, reverse=True))}
    return [(levels[size], page_no, text) for page_no, _, size, text in candidates]


def parse_pdf(data: bytes) -> list[ParsedSection]:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ParseError("could not open the PDF") from exc
    with doc:
        if doc.needs_pass:
            raise ParseError("the PDF is password protected")
        if not len(doc):
            raise ParseError("the PDF has no pages")
        lines = _visible_lines(doc)
        pages = [" ".join(line[4] for line in lines if line[0] == page_no) for page_no in range(len(doc))]
        entries = _toc_entries(doc, len(pages)) or _font_entries(lines)
    if entries:
        return _assemble(pages, _boundaries(entries, pages))
    return _assemble(pages, [_Boundary(i, 0, 0, 1, f"Page {i + 1}") for i in range(len(pages))])


def _txt_heading_level(line: str, previous_blank: bool) -> int | None:
    if len(line) > MAX_TXT_HEADING_CHARS or line.endswith((".", ",", ";", ":", "?", "!")):
        return None
    numbered = _NUMBERED.match(line)
    if numbered:
        return numbered.group(1).count(".") + 1
    words = [w for w in line.split() if any(c.isalpha() for c in w)]
    # A wrapped sentence can look Title Case by chance, so require a blank line first.
    if previous_blank and words and len(words) <= 10:
        capitalised = sum(w[0].isupper() for w in words)
        if capitalised / len(words) >= 0.8:
            return 1
    return None


def parse_txt(text: str, filename: str = "Document") -> list[ParsedSection]:
    heading, level = None, 1
    body: list[str] = []
    found: list[tuple[str | None, int, str]] = []
    previous_blank = True
    skipping = False
    for raw in text.splitlines():
        line = normalize(raw)
        if _is_footer(line):
            continue
        if _is_skipped_heading(line):
            skipping, previous_blank = True, False
            continue
        heading_level = _txt_heading_level(line, previous_blank) if line else None
        if heading_level is not None:
            skipping = False
            found.append((heading, level, normalize(" ".join(body))))
            heading, level, body = line, heading_level, []
        elif line and not skipping:
            body.append(line)
        previous_blank = not line
    found.append((heading, level, normalize(" ".join(body))))

    # The text before the first heading only counts if there is some.
    if found[0][0] is None and not found[0][2]:
        found = found[1:]
    sections = [
        ParsedSection(
            heading=h or (filename if len(found) == 1 else "Introduction"),
            level=lvl,
            position=i,
            page_start=1,
            page_end=1,
            text=body_text,
            page_map=[(0, 1)] if body_text else [],
        )
        for i, (h, lvl, body_text) in enumerate(found)
    ]
    _link_parents(sections)
    return sections


def parse_document(filename: str, data: bytes) -> list[ParsedSection]:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(data)
    if suffix == ".txt":
        try:
            return parse_txt(data.decode("utf-8-sig"), filename)
        except UnicodeDecodeError as exc:
            raise ParseError("the text file is not UTF-8") from exc
    raise ParseError(f"unsupported file type: {suffix}")
