"""
Generate PROJECT_DEEP_DIVE.pdf from PROJECT_DEEP_DIVE.md using ReportLab.
Run: python generate_pdf.py
"""

import re
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, Preformatted, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

MD_FILE = Path(__file__).parent / "PROJECT_DEEP_DIVE.md"
PDF_FILE = Path(__file__).parent / "PROJECT_DEEP_DIVE.pdf"

# ── Colour palette ────────────────────────────────────────────────────────────
C_BG        = colors.HexColor("#0f1117")
C_ACCENT    = colors.HexColor("#4f8ef7")
C_ACCENT2   = colors.HexColor("#7c5cbf")
C_TEXT      = colors.HexColor("#e2e8f0")
C_MUTED     = colors.HexColor("#94a3b8")
C_CODE_BG   = colors.HexColor("#1e2433")
C_BORDER    = colors.HexColor("#2d3748")
C_WHITE     = colors.white
C_H1_LINE   = colors.HexColor("#4f8ef7")

# ── Styles ────────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

def make_style(name, **kw):
    return ParagraphStyle(name, **kw)

S_H1 = make_style("H1",
    fontSize=26, leading=32, textColor=C_WHITE,
    fontName="Helvetica-Bold", spaceAfter=6, spaceBefore=20,
    alignment=TA_LEFT)

S_H2 = make_style("H2",
    fontSize=16, leading=22, textColor=C_ACCENT,
    fontName="Helvetica-Bold", spaceAfter=4, spaceBefore=18)

S_H3 = make_style("H3",
    fontSize=12, leading=16, textColor=C_ACCENT2,
    fontName="Helvetica-Bold", spaceAfter=3, spaceBefore=12)

S_BODY = make_style("Body",
    fontSize=9.5, leading=15, textColor=C_TEXT,
    fontName="Helvetica", spaceAfter=4, spaceBefore=0)

S_BULLET = make_style("Bullet",
    fontSize=9.5, leading=15, textColor=C_TEXT,
    fontName="Helvetica", leftIndent=16, spaceAfter=2,
    bulletIndent=6, bulletFontName="Helvetica")

S_BULLET2 = make_style("Bullet2",
    fontSize=9, leading=14, textColor=C_MUTED,
    fontName="Helvetica", leftIndent=32, spaceAfter=2,
    bulletIndent=22, bulletFontName="Helvetica")

S_CODE = make_style("Code",
    fontSize=8, leading=12, textColor=colors.HexColor("#a8d8a8"),
    fontName="Courier", leftIndent=12, rightIndent=12,
    spaceAfter=6, spaceBefore=4, backColor=C_CODE_BG)

S_BOLD_Q = make_style("BoldQ",
    fontSize=9.5, leading=15, textColor=C_ACCENT,
    fontName="Helvetica-Bold", spaceAfter=2, spaceBefore=8)

S_SUBTITLE = make_style("Subtitle",
    fontSize=11, leading=16, textColor=C_MUTED,
    fontName="Helvetica", spaceAfter=2, alignment=TA_CENTER)

# ── Table style ───────────────────────────────────────────────────────────────
TABLE_STYLE = TableStyle([
    ("BACKGROUND",   (0, 0), (-1, 0),  colors.HexColor("#1a2035")),
    ("TEXTCOLOR",    (0, 0), (-1, 0),  C_ACCENT),
    ("FONTNAME",     (0, 0), (-1, 0),  "Helvetica-Bold"),
    ("FONTSIZE",     (0, 0), (-1, 0),  9),
    ("BOTTOMPADDING",(0, 0), (-1, 0),  6),
    ("TOPPADDING",   (0, 0), (-1, 0),  6),
    ("BACKGROUND",   (0, 1), (-1, -1), C_CODE_BG),
    ("TEXTCOLOR",    (0, 1), (-1, -1), C_TEXT),
    ("FONTNAME",     (0, 1), (-1, -1), "Helvetica"),
    ("FONTSIZE",     (0, 1), (-1, -1), 8.5),
    ("ROWBACKGROUNDS",(0,1), (-1,-1),  [C_CODE_BG, colors.HexColor("#161d2e")]),
    ("GRID",         (0, 0), (-1, -1), 0.4, C_BORDER),
    ("LEFTPADDING",  (0, 0), (-1, -1), 8),
    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ("TOPPADDING",   (0, 1), (-1, -1), 5),
    ("BOTTOMPADDING",(0, 1), (-1, -1), 5),
    ("VALIGN",       (0, 0), (-1, -1), "TOP"),
])

# ── Markdown parser ───────────────────────────────────────────────────────────

def escape(text):
    """Escape ReportLab XML special chars."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def inline_fmt(text):
    """Convert inline markdown (bold, code, italic) to ReportLab XML."""
    text = escape(text)
    # Inline code first — replace with placeholder to protect from other regex
    code_spans = {}
    def save_code(m):
        key = f"\x00CODE{len(code_spans)}\x00"
        code_spans[key] = f'<font name="Courier" color="#a8d8a8">{escape(m.group(1))}</font>'
        return key
    text = re.sub(r'`([^`]+)`', save_code, text)
    # Bold+italic ***text***
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<b><i>\1</i></b>', text)
    # Bold **text**
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # Italic *text* — only match single * not followed by another *
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    # Restore code spans
    for key, val in code_spans.items():
        text = text.replace(key, val)
    return text

def parse_md(md_text):
    """Parse markdown into a list of ReportLab flowables."""
    flowables = []
    lines = md_text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]

        # ── Horizontal rule ───────────────────────────────────────────────────
        if re.match(r'^---+$', line.strip()):
            flowables.append(Spacer(1, 4))
            flowables.append(HRFlowable(width="100%", thickness=0.5,
                                        color=C_BORDER, spaceAfter=4))
            i += 1
            continue

        # ── Headings ──────────────────────────────────────────────────────────
        if line.startswith("# ") and not line.startswith("## "):
            text = inline_fmt(line[2:].strip())
            flowables.append(Spacer(1, 8))
            flowables.append(Paragraph(text, S_H1))
            flowables.append(HRFlowable(width="100%", thickness=1.5,
                                        color=C_H1_LINE, spaceAfter=6))
            i += 1
            continue

        if line.startswith("## "):
            text = inline_fmt(line[3:].strip())
            flowables.append(Spacer(1, 6))
            flowables.append(Paragraph(text, S_H2))
            flowables.append(HRFlowable(width="100%", thickness=0.5,
                                        color=C_BORDER, spaceAfter=4))
            i += 1
            continue

        if line.startswith("### "):
            text = inline_fmt(line[4:].strip())
            flowables.append(Paragraph(text, S_H3))
            i += 1
            continue

        # ── Fenced code block ─────────────────────────────────────────────────
        if line.strip().startswith("```"):
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            code_text = "\n".join(code_lines)
            flowables.append(Preformatted(code_text, S_CODE))
            continue

        # ── Table ─────────────────────────────────────────────────────────────
        if line.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].startswith("|"):
                table_lines.append(lines[i])
                i += 1
            # Filter out separator rows (|---|---|)
            rows = []
            for tl in table_lines:
                if re.match(r'^\|[-| :]+\|$', tl.strip()):
                    continue
                cells = [c.strip() for c in tl.strip().strip("|").split("|")]
                rows.append(cells)
            if rows:
                # Wrap cells in Paragraphs
                col_count = max(len(r) for r in rows)
                # Normalize row lengths
                rows = [r + [""] * (col_count - len(r)) for r in rows]
                para_rows = []
                for ri, row in enumerate(rows):
                    style = make_style(f"TH{ri}",
                        fontSize=9 if ri == 0 else 8.5,
                        leading=13,
                        textColor=C_ACCENT if ri == 0 else C_TEXT,
                        fontName="Helvetica-Bold" if ri == 0 else "Helvetica")
                    para_rows.append([
                        Paragraph(inline_fmt(cell), style) for cell in row
                    ])
                # Distribute column widths
                page_w = A4[0] - 3.5*cm
                col_w = page_w / col_count
                t = Table(para_rows, colWidths=[col_w]*col_count,
                          repeatRows=1, hAlign="LEFT")
                t.setStyle(TABLE_STYLE)
                flowables.append(Spacer(1, 4))
                flowables.append(t)
                flowables.append(Spacer(1, 6))
            continue

        # ── Bullet points ─────────────────────────────────────────────────────
        m = re.match(r'^(\s*)[-*] (.+)', line)
        if m:
            indent = len(m.group(1))
            text = inline_fmt(m.group(2))
            style = S_BULLET2 if indent >= 2 else S_BULLET
            bullet = "◦" if indent >= 2 else "•"
            flowables.append(Paragraph(f"{bullet}  {text}", style))
            i += 1
            continue

        # ── Numbered list ─────────────────────────────────────────────────────
        m = re.match(r'^\d+\. (.+)', line)
        if m:
            text = inline_fmt(m.group(1))
            flowables.append(Paragraph(f"•  {text}", S_BULLET))
            i += 1
            continue

        # ── Q&A bold question lines ───────────────────────────────────────────
        if line.startswith("**Q:"):
            text = inline_fmt(line.strip())
            flowables.append(Paragraph(text, S_BOLD_Q))
            i += 1
            continue

        # ── Empty line ────────────────────────────────────────────────────────
        if line.strip() == "":
            flowables.append(Spacer(1, 4))
            i += 1
            continue

        # ── Normal paragraph ──────────────────────────────────────────────────
        text = inline_fmt(line.strip())
        if text:
            flowables.append(Paragraph(text, S_BODY))
        i += 1

    return flowables


# ── Build PDF ─────────────────────────────────────────────────────────────────

def build_pdf():
    doc = SimpleDocTemplate(
        str(PDF_FILE),
        pagesize=A4,
        leftMargin=1.8*cm,
        rightMargin=1.8*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
        title="DeployHub — Technical Deep Dive",
        author="DeployHub",
    )

    def on_page(canvas, doc):
        canvas.saveState()
        # Dark background
        canvas.setFillColor(C_BG)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        # Footer
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(C_MUTED)
        canvas.drawCentredString(A4[0]/2, 1.2*cm,
            f"DeployHub — Technical Deep Dive  |  Page {doc.page}")
        # Top accent bar
        canvas.setFillColor(C_ACCENT)
        canvas.rect(0, A4[1]-3, A4[0], 3, fill=1, stroke=0)
        canvas.restoreState()

    md_text = MD_FILE.read_text(encoding="utf-8")
    flowables = parse_md(md_text)

    doc.build(flowables, onFirstPage=on_page, onLaterPages=on_page)
    print(f"✅  PDF written to: {PDF_FILE}")


if __name__ == "__main__":
    build_pdf()
