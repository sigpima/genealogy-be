"""The "quyển phả": a printable multi-page PDF of the family (see the GĐ10 design). Pure ReportLab, no I/O of its own:
the router gathers the data and calls `build_book` in a worker thread.

Fonts are the DejaVu Serif/Sans files bundled in app/assets/fonts (they cover Vietnamese), never anything from the host.
"""

import io
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    HRFlowable,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus import Image as RLImage
from reportlab.platypus.tableofcontents import TableOfContents

from app.core.tree_layout import TreeLayout
from app.models.article import Article, GenerationWord, TimelineEntry
from app.models.member import Member
from app.models.place import Place

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
PRIMARY = colors.HexColor("#8B1A1A")
GOLD = colors.HexColor("#C59B27")
INK = colors.HexColor("#2A2118")
MUTED = colors.HexColor("#6B5E4E")
PAPER = colors.HexColor("#F6EFE3")

MAX_DIAGRAM_LEAVES = 14
MAX_DIAGRAM_DEPTH = 4
KIND_TITLES = {"precepts": "Tộc ước & gia huấn"}


@dataclass
class BookOptions:
    chronicles: bool = True
    profiles: bool = True
    diagram: bool = True
    notes: bool = True
    photos: bool = False
    contacts: bool = False
    max_generation: int | None = None


@dataclass
class BookData:
    tree_name: str
    layout: TreeLayout
    #: member id -> [(spouse, marriage year)]
    spouses_of: dict[int, list[tuple[Member, int | None]]]
    articles: list[Article]  # published only, in reading order
    timeline: list[TimelineEntry]
    words: list[GenerationWord]
    #: branch id -> (name, colour)
    branches: dict[int, tuple[str, str]]
    places: dict[int, Place]
    avatar_paths: dict[int, Path]
    generated_on: date
    options: BookOptions = field(default_factory=BookOptions)


_fonts_ready = False


def _register_fonts() -> None:
    global _fonts_ready
    if _fonts_ready:
        return
    for name, file in (
        ("Serif", "DejaVuSerif.ttf"),
        ("Serif-Bold", "DejaVuSerif-Bold.ttf"),
        ("Sans", "DejaVuSans.ttf"),
        ("Sans-Bold", "DejaVuSans-Bold.ttf"),
    ):
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
    pdfmetrics.registerFontFamily("Serif", normal="Serif", bold="Serif-Bold", italic="Serif", boldItalic="Serif-Bold")
    pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold", italic="Sans", boldItalic="Sans-Bold")
    _fonts_ready = True


def _styles() -> dict[str, ParagraphStyle]:
    base = dict(fontName="Serif", textColor=INK, leading=15, fontSize=10.5)
    return {
        "body": ParagraphStyle("body", spaceAfter=6, **base),
        "h1": ParagraphStyle("h1", **{**base, "fontName": "Serif-Bold", "fontSize": 22, "leading": 28, "textColor": PRIMARY}, spaceBefore=6, spaceAfter=12),
        "h2": ParagraphStyle("h2", **{**base, "fontName": "Serif-Bold", "fontSize": 15, "leading": 20, "textColor": PRIMARY}, spaceBefore=14, spaceAfter=6),
        "h3": ParagraphStyle("h3", **{**base, "fontName": "Serif-Bold", "fontSize": 12, "leading": 16}, spaceBefore=8, spaceAfter=4),
        "quote": ParagraphStyle("quote", **{**base, "textColor": MUTED}, leftIndent=18, borderPadding=4, spaceAfter=8),
        "name": ParagraphStyle("name", **{**base, "fontName": "Serif-Bold", "fontSize": 12, "leading": 15}),
        "meta": ParagraphStyle("meta", **{**base, "fontName": "Sans", "fontSize": 8.5, "leading": 12, "textColor": MUTED}),
        "line": ParagraphStyle("line", **{**base, "fontSize": 9.5, "leading": 13}),
        "toc1": ParagraphStyle("toc1", **{**base, "fontName": "Serif-Bold", "fontSize": 11.5}, leftIndent=0, spaceBefore=6),
        "toc2": ParagraphStyle("toc2", **{**base, "fontSize": 10}, leftIndent=14),
    }


def _p(text: str) -> str:
    return escape(text or "")


# --------------------------------------------------------------------------- text helpers


def _pad(n: int) -> str:
    return f"{n:02d}"


def partial_date(year: int | None, month: int | None, day: int | None, lunar: bool, leap: bool) -> str | None:
    """"15/08/1945", "08/1945", "15/08", "1945"; a lunar date adds " âm lịch" (same rules as the web app)."""
    if year is None and month is None and day is None:
        return None
    if month is None and day is None:
        return str(year)
    parts = []
    if day is not None:
        parts.append(_pad(day))
    if month is not None:
        parts.append(_pad(month))
    if year is not None:
        parts.append(str(year))
    text = "/".join(parts)
    if month is not None and lunar:
        text += " âm lịch" + (" (tháng nhuận)" if leap else "")
    return text


def life_text(m: Member) -> str:
    parts = []
    born = partial_date(m.birth_year, m.birth_month, m.birth_day, m.birth_is_lunar, m.birth_leap_month)
    died = partial_date(m.death_year, m.death_month, m.death_day, m.death_is_lunar, m.death_leap_month)
    if born:
        parts.append(f"Sinh {born}")
    if died:
        parts.append(f"Mất {died}")
    if m.death_is_lunar and m.death_month is not None and m.death_day is not None:
        parts.append(f"giỗ {_pad(m.death_day)}/{_pad(m.death_month)} âm lịch")
    return " · ".join(parts)


def short_years(m: Member) -> str:
    if m.birth_year is None and m.death_year is None:
        return ""
    return f"{m.birth_year or '?'} – {m.death_year or ''}".rstrip(" ")


def _inline(text: str) -> str:
    """A line of Markdown as ReportLab paragraph markup: only **bold** survives, links and images become their text."""
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    out = escape(text)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)
    out = re.sub(r"__([^_]+)__", r"<b>\1</b>", out)
    out = re.sub(r"(?<!\w)[*_]([^*_\s][^*_]*)[*_](?!\w)", r"\1", out)
    return re.sub(r"`([^`]+)`", r"\1", out)


def markdown_flowables(body: str, st: dict[str, ParagraphStyle]) -> list[Flowable]:
    out: list[Flowable] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append(Paragraph(_inline(" ".join(paragraph)), st["body"]))
            paragraph.clear()

    for raw in body.replace("\r\n", "\n").split("\n"):
        line = raw.rstrip()
        if not line.strip():
            flush()
        elif m := re.match(r"^(#{1,4})\s+(.*)$", line):
            flush()
            out.append(Paragraph(_inline(m.group(2)), st["h2"] if len(m.group(1)) <= 2 else st["h3"]))
        elif re.match(r"^\s*([-*_])(\s*\1){2,}\s*$", line):
            flush()
            out.append(HRFlowable(width="100%", color=GOLD, spaceBefore=4, spaceAfter=8))
        elif m := re.match(r"^\s*[-*+]\s+(.*)$", line):
            flush()
            out.append(Paragraph(_inline(m.group(1)), st["body"], bulletText="•"))
        elif m := re.match(r"^\s*(\d+)[.)]\s+(.*)$", line):
            flush()
            out.append(Paragraph(_inline(m.group(2)), st["body"], bulletText=f"{m.group(1)}."))
        elif m := re.match(r"^\s*>\s?(.*)$", line):
            flush()
            out.append(Paragraph(_inline(m.group(1)), st["quote"]))
        else:
            paragraph.append(line.strip())
    flush()
    return out


# --------------------------------------------------------------------------- the tree diagram


@dataclass
class DNode:
    member: Member
    children: list["DNode"] = field(default_factory=list)
    more: bool = False  # has descendants that are not drawn on this page


def _width(node: DNode) -> int:
    return 1 if not node.children else sum(_width(c) for c in node.children)


def _kids(layout: TreeLayout, member: Member, limit: int | None) -> list[Member]:
    kids = layout.children.get(member.id, [])
    return kids if limit is None else [k for k in kids if layout.generation[k.id] <= limit]


def _build(layout: TreeLayout, member: Member, depth: int, limit: int | None) -> DNode:
    kids = _kids(layout, member, limit)
    if depth == 0 or not kids:
        return DNode(member, [], more=bool(kids))
    return DNode(member, [_build(layout, k, depth - 1, limit) for k in kids])


def diagram_pages(layout: TreeLayout, max_generation: int | None) -> list[tuple[DNode, str]]:
    """Split the tree into pages that stay readable: a (sub)tree too wide or too deep is cut and its cut-off children get their own pages."""
    pages: list[tuple[DNode, str]] = []
    queue: list[tuple[Member, str]] = [(m, "") for m in layout.children.get(None, [])]
    while queue:
        root, suffix = queue.pop(0)
        depth = MAX_DIAGRAM_DEPTH
        node = _build(layout, root, depth, max_generation)
        while _width(node) > MAX_DIAGRAM_LEAVES and depth > 1:
            depth -= 1
            node = _build(layout, root, depth, max_generation)
        chunks: list[DNode] = [node]
        if _width(node) > MAX_DIAGRAM_LEAVES:  # a person with a great many children: spread them over several pages
            kids = _kids(layout, root, max_generation)
            chunks = [DNode(root, [DNode(k, [], more=bool(_kids(layout, k, max_generation))) for k in kids[i : i + MAX_DIAGRAM_LEAVES]]) for i in range(0, len(kids), MAX_DIAGRAM_LEAVES)]
        for index, chunk in enumerate(chunks):
            label = suffix + (f" (phần {index + 1}/{len(chunks)})" if len(chunks) > 1 else "")
            pages.append((chunk, label))
            stack = [chunk]
            while stack:
                n = stack.pop()
                if n is not chunk and n.more:
                    queue.append((n.member, ""))
                stack.extend(n.children)
    return pages


CARD_W, CARD_H, GAP_X, GAP_Y = 88.0, 38.0, 12.0, 34.0


class TreeDiagram(Flowable):
    """One diagram page. Drawn at natural size, then scaled down to the frame."""

    def __init__(self, root: DNode, layout: TreeLayout, branches: dict[int, tuple[str, str]], avail_w: float, avail_h: float, max_generation: int | None):
        super().__init__()
        self.root, self.layout, self.branches, self.max_generation = root, layout, branches, max_generation
        self.depth = self._depth(root)
        self.nat_w = _width(root) * (CARD_W + GAP_X) - GAP_X
        self.nat_h = (self.depth + 1) * CARD_H + self.depth * GAP_Y + 12
        self.scale = min(avail_w / self.nat_w, avail_h / self.nat_h, 1.0)
        self.width, self.height = self.nat_w * self.scale, self.nat_h * self.scale

    def _depth(self, node: DNode) -> int:
        return 0 if not node.children else 1 + max(self._depth(c) for c in node.children)

    def wrap(self, avail_w: float, avail_h: float) -> tuple[float, float]:
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        c.saveState()
        c.scale(self.scale, self.scale)
        self._place(self.root, 0, 0)
        c.restoreState()

    def _place(self, node: DNode, depth: int, first_column: int) -> float:
        """Draw `node` and its subtree; returns the node's x centre."""
        c = self.canv
        y_top = self.nat_h - depth * (CARD_H + GAP_Y)
        if not node.children:
            cx = first_column * (CARD_W + GAP_X) + CARD_W / 2
            self._card(node, cx, y_top)
            return cx
        centres, column = [], first_column
        for child in node.children:
            centres.append(self._place(child, depth + 1, column))
            column += _width(child)
        cx = (centres[0] + centres[-1]) / 2
        self._card(node, cx, y_top)
        c.setStrokeColor(MUTED)
        c.setLineWidth(0.8)
        bottom, mid, child_top = y_top - CARD_H, y_top - CARD_H - GAP_Y / 2, y_top - CARD_H - GAP_Y
        c.line(cx, bottom, cx, mid)
        c.line(centres[0], mid, centres[-1], mid)
        for x in centres:
            c.line(x, mid, x, child_top)
        return cx

    def _card(self, node: DNode, cx: float, y_top: float) -> None:
        c, m = self.canv, node.member
        x, y = cx - CARD_W / 2, y_top - CARD_H
        branch = self.branches.get(self.layout.branch_of.get(m.id) or -1)
        c.setFillColor(colors.white)
        c.setStrokeColor(PRIMARY if m.death_year is None and m.birth_year is not None else MUTED)
        c.setLineWidth(1)
        c.roundRect(x, y, CARD_W, CARD_H, 4, stroke=1, fill=1)
        if branch:
            c.setFillColor(colors.HexColor(branch[1]))
            c.roundRect(x + 2, y + 4, 3, CARD_H - 8, 1.5, stroke=0, fill=1)
        c.setFillColor(INK)
        lines = self._wrap_name(m.full_name, CARD_W - 12)
        c.setFont("Serif-Bold", 7.2)
        top = y + CARD_H - 10
        for i, line in enumerate(lines[:2]):
            c.drawCentredString(cx + 2, top - i * 8.4, line)
        years = short_years(m)
        if years:
            c.setFont("Sans", 6.2)
            c.setFillColor(MUTED)
            c.drawCentredString(cx + 2, y + 4.5, years)
        if node.more:
            c.setFillColor(PRIMARY)
            c.setFont("Sans", 6.5)
            c.drawCentredString(cx, y - 8, "▼ xem tiếp")

    @staticmethod
    def _wrap_name(name: str, width: float) -> list[str]:
        words, lines, current = name.split(), [], ""
        for word in words:
            trial = f"{current} {word}".strip()
            if stringWidth(trial, "Serif-Bold", 7.2) <= width or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        if len(lines) > 2:  # keep the last word(s) (the given name) visible
            lines = [lines[0], "… " + " ".join(lines[-1:])]
        return lines


# --------------------------------------------------------------------------- the document


class _Doc(BaseDocTemplate):
    def afterFlowable(self, flowable: Flowable) -> None:  # noqa: N802 (ReportLab hook)
        level = getattr(flowable, "_toc_level", None)
        if level is not None:
            text = flowable.getPlainText()
            key = f"toc-{self.seq.nextf('toc')}"
            self.canv.bookmarkPage(key)
            self.notify("TOCEntry", (level, text, self.page, key))


def _heading(text: str, style: ParagraphStyle, level: int) -> Paragraph:
    p = Paragraph(_p(text), style)
    p._toc_level = level  # type: ignore[attr-defined]
    return p


def _cover(canvas, doc, data: BookData) -> None:
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, w, h, stroke=0, fill=1)
    for inset, width, color in ((14 * mm, 3.2, PRIMARY), (18 * mm, 1.0, GOLD)):
        canvas.setStrokeColor(color)
        canvas.setLineWidth(width)
        canvas.rect(inset, inset, w - 2 * inset, h - 2 * inset, stroke=1, fill=0)
    canvas.setFillColor(PRIMARY)
    canvas.setFont("Serif-Bold", 15)
    canvas.drawCentredString(w / 2, h - 52 * mm, "G I A   P H Ả")
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(1.2)
    canvas.line(w / 2 - 38 * mm, h - 58 * mm, w / 2 + 38 * mm, h - 58 * mm)
    name = data.tree_name
    size = 34 if stringWidth(name, "Serif-Bold", 34) < w - 60 * mm else 24
    canvas.setFont("Serif-Bold", size)
    canvas.setFillColor(INK)
    canvas.drawCentredString(w / 2, h / 2 + 8 * mm, name)
    canvas.setFont("Serif", 12)
    canvas.setFillColor(MUTED)
    canvas.drawCentredString(w / 2, h / 2 - 6 * mm, "Phả hệ · Sử ký · Tộc ước")
    canvas.setFont("Sans", 9)
    canvas.drawCentredString(w / 2, 32 * mm, f"Biên soạn ngày {data.generated_on:%d/%m/%Y}")
    canvas.restoreState()


def _footer(canvas, doc, data: BookData) -> None:
    w, _ = canvas._pagesize
    canvas.saveState()
    canvas.setFont("Sans", 8)
    canvas.setFillColor(MUTED)
    canvas.drawCentredString(w / 2, 12 * mm, f"Gia phả {data.tree_name} — trang {doc.page}")
    canvas.restoreState()


def _thumb(path: Path, size: int = 90) -> io.BytesIO | None:
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            side = min(image.size)
            left, top = (image.width - side) // 2, (image.height - side) // 2
            image = image.crop((left, top, left + side, top + side)).resize((size, size))
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=80)
            buffer.seek(0)
            return buffer
    except Exception:  # noqa: BLE001 - a missing or broken photo must not break the whole book
        return None


def _profile(m: Member, data: BookData, st: dict[str, ParagraphStyle]) -> Flowable:
    layout, o = data.layout, data.options
    lines: list[Flowable] = []
    branch = data.branches.get(layout.branch_of.get(m.id) or -1)
    head = f"{_p(m.full_name)}" + (f' <font name="Sans" size="8" color="#6B5E4E"> · {_p(branch[0])}</font>' if branch else "")
    lines.append(Paragraph(head, st["name"]))
    parent = layout.by_id.get(m.parent_id) if m.parent_id is not None else None
    if parent:
        mother = layout.by_id.get(m.mother_id) if m.mother_id is not None else None
        lines.append(Paragraph("Con của " + _p(parent.full_name) + (f" và {_p(mother.full_name)}" if mother else "") + (" (con nuôi)" if m.is_adopted else ""), st["meta"]))
    if m.courtesy_name or m.title:
        lines.append(Paragraph(_p(" · ".join(x for x in (f"Tự: {m.courtesy_name}" if m.courtesy_name else "", m.title or "") if x)), st["line"]))
    life = life_text(m)
    if life:
        lines.append(Paragraph(_p(life), st["line"]))
    place_bits = [x for x in (f"Quê quán: {m.hometown}" if m.hometown else "", f"Nơi ở: {m.residence}" if m.residence else "") if x]
    if place_bits:
        lines.append(Paragraph(_p(" · ".join(place_bits)), st["line"]))
    for spouse, year in data.spouses_of.get(m.id, []):
        extra = "; ".join(x for x in (short_years(spouse), f"kết hôn {year}" if year else "") if x)
        lines.append(Paragraph("Vợ/chồng: " + _p(spouse.full_name) + (f" ({_p(extra)})" if extra else ""), st["line"]))
    kids = _kids(layout, m, o.max_generation)
    if kids:
        lines.append(Paragraph("Con: " + _p(", ".join(k.full_name for k in kids)), st["line"]))
    rest = data.places.get(m.burial_place_id) if m.burial_place_id is not None else None
    if rest or m.burial_plot:
        lines.append(Paragraph("An nghỉ: " + _p(", ".join(x for x in (rest.name if rest else "", m.burial_plot or "") if x)), st["line"]))
    if o.contacts and (m.phone or m.email):
        lines.append(Paragraph("Liên hệ: " + _p(" · ".join(x for x in (m.phone, m.email) if x)), st["line"]))
    if o.notes and m.notes:
        lines.append(Paragraph(_p(m.notes).replace("\n", "<br/>"), st["body"]))
    photo = _thumb(data.avatar_paths[m.id]) if o.photos and m.id in data.avatar_paths else None
    if photo is not None:
        table = Table([[RLImage(photo, 22 * mm, 22 * mm), lines]], colWidths=[26 * mm, None])
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        block: Flowable = table
    else:
        block = Table([[lines]], colWidths=[None])
        block.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return KeepTogether([block, HRFlowable(width="100%", color=colors.HexColor("#E3D9C6"), spaceBefore=3, spaceAfter=7)])


def build_book(data: BookData) -> bytes:
    _register_fonts()
    st = _styles()
    o = data.options
    buffer = io.BytesIO()
    margin = 20 * mm
    doc = _Doc(
        buffer,
        pagesize=A4,
        title=f"Gia phả {data.tree_name}",
        author=data.tree_name,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=margin + 4 * mm,
    )
    a4w, a4h = A4
    a3w, a3h = landscape(A3)
    body_frame = Frame(margin, margin + 4 * mm, a4w - 2 * margin, a4h - 2 * margin - 4 * mm, id="body")
    wide_margin = 28
    wide_frame = Frame(wide_margin, wide_margin + 14, a3w - 2 * wide_margin, a3h - 2 * wide_margin - 14, id="wide")
    cover_frame = Frame(margin, margin, a4w - 2 * margin, a4h - 2 * margin, id="cover")
    doc.addPageTemplates(
        [
            PageTemplate(id="cover", frames=[cover_frame], pagesize=A4, onPage=lambda c, d: _cover(c, d, data)),
            PageTemplate(id="body", frames=[body_frame], pagesize=A4, onPage=lambda c, d: _footer(c, d, data)),
            PageTemplate(id="wide", frames=[wide_frame], pagesize=landscape(A3), onPage=lambda c, d: _footer(c, d, data)),
        ]
    )

    story: list[Flowable] = [NextPageTemplate("body"), PageBreak()]
    toc = TableOfContents()
    toc.levelStyles = [st["toc1"], st["toc2"]]
    toc.dotsMinLevel = 0
    story += [Paragraph("Mục lục", st["h1"]), toc, PageBreak()]

    if o.chronicles:
        precepts = [a for a in data.articles if a.kind == "precepts"]
        others = [a for a in data.articles if a.kind != "precepts"]
        for group_title, group in ((KIND_TITLES["precepts"], precepts), ("Sử ký dòng họ", others)):
            if not group:
                continue
            story.append(_heading(group_title, st["h1"], 0))
            for article in group:
                story.append(_heading(article.title, st["h2"], 1))
                story += markdown_flowables(article.body, st)
            story.append(PageBreak())
        if data.words:
            story.append(_heading("Chữ đệm các đời (bài đệm)", st["h1"], 0))
            rows = [[Paragraph(f"Đời {w.generation}", st["body"]), Paragraph(f"<b>{_p(w.word)}</b>", st["body"]), Paragraph(_p(w.meaning or ""), st["body"])] for w in data.words]
            table = Table(rows, colWidths=[28 * mm, 40 * mm, None])
            table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E3D9C6")), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [table, PageBreak()]
        if data.timeline:
            story.append(_heading("Dòng thời gian", st["h1"], 0))
            for entry in data.timeline:
                when = partial_date(entry.year, entry.month, entry.day, False, False)
                story.append(Paragraph(f"<b>{_p(when or '')}</b> — {_p(entry.title)}", st["body"]))
                if entry.body:
                    story.append(Paragraph(_p(entry.body), st["meta"]))
            story.append(PageBreak())

    layout = data.layout
    top = max((layout.generation[m.id] for m in layout.order), default=0)
    if o.max_generation is not None:
        top = min(top, o.max_generation)
    if o.profiles:
        story.append(_heading("Phả hệ theo đời", st["h1"], 0))
        word_of = {w.generation: w for w in data.words}
        for generation in range(1, top + 1):
            people = [m for m in layout.order if layout.generation[m.id] == generation]
            if not people:
                continue
            word = word_of.get(generation)
            story.append(_heading(f"Đời {generation}" + (f" — chữ đệm {word.word}" if word else ""), st["h2"], 1))
            story.append(Paragraph(f"{len(people)} người", st["meta"]))
            story.append(Spacer(1, 4))
            for member in people:
                story.append(_profile(member, data, st))
        story.append(PageBreak())

    if o.diagram:
        pages = diagram_pages(layout, o.max_generation)
        story += [NextPageTemplate("wide"), PageBreak()] if story and not isinstance(story[-1], PageBreak) else [NextPageTemplate("wide"), PageBreak()]
        story.append(_heading("Phả đồ", st["h1"], 0))
        story.append(Paragraph("Mỗi trang là một nhánh; “▼ xem tiếp” nghĩa là con cháu của người đó có trang riêng ở phía sau. Vạch màu bên trái thẻ là màu của chi.", st["meta"]))
        avail_w, avail_h = a3w - 2 * wide_margin - 6, a3h - 2 * wide_margin - 14 - 90
        for root, label in pages:
            gen = layout.generation[root.member.id]
            title = Paragraph(_p(f"Nhánh {root.member.full_name} (đời {gen}){label}"), st["h3"])
            # small branches share a page: the frames flow, KeepTogether only prevents a branch from being cut in two
            story.append(KeepTogether([title, TreeDiagram(root, layout, data.branches, avail_w, avail_h, o.max_generation), Spacer(1, 16)]))

    if not o.chronicles and not o.profiles and not o.diagram:
        story.append(Paragraph("Chưa chọn nội dung nào để in.", st["body"]))
    doc.multiBuild(story)
    return buffer.getvalue()
