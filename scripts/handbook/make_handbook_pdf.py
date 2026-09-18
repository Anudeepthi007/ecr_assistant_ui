"""Build a compact, text-only PDF handbook of the ECR Assistant project.

No third-party libraries: pages are written directly, using the PDF standard
fonts (nothing embedded) and Flate-compressed text streams, so the file stays
small enough to upload anywhere.
"""
from __future__ import annotations

import re
import zlib
from datetime import date
from pathlib import Path

OUT = Path(r"C:\Users\aatmakur\Documents\ecr_assistant_ui\docs\ECR-Assistant-Project-Handbook.pdf")

PAGE_W, PAGE_H = 595.28, 841.89          # A4
M_L, M_R, M_T, M_B = 56, 50, 58, 52
BODY_W = PAGE_W - M_L - M_R
FONTS = {"F1": "Helvetica", "F2": "Helvetica-Bold", "F3": "Courier", "F4": "Helvetica-Oblique"}
WIDTH_FACTOR = {"F1": 0.505, "F2": 0.535, "F3": 0.600, "F4": 0.505}

SUBS = {"\u2014": "-", "\u2013": "-", "\u2018": "'", "\u2019": "'", "\u201c": '"',
        "\u201d": '"', "\u2026": "...", "\u00b7": "-", "\u2192": "->", "\u2265": ">=",
        "\u00d7": "x", "\u2022": "-"}


def clean(text: str) -> str:
    for bad, good in SUBS.items():
        text = text.replace(bad, good)
    return "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in text)


def esc(text: str) -> str:
    return clean(text).replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def text_width(text: str, size: float, font: str) -> float:
    return len(text) * size * WIDTH_FACTOR[font]


def wrap(text: str, size: float, font: str, width: float) -> list[str]:
    words, lines, line = clean(text).split(), [], ""
    for word in words:
        trial = f"{line} {word}".strip()
        if text_width(trial, size, font) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [""]


class Doc:
    """Page builder: a cursor that flows text down pages."""

    def __init__(self) -> None:
        self.pages: list[list[str]] = []
        self.ops: list[str] = []
        self.y = PAGE_H - M_T
        self.sections: list[tuple[int, str, int]] = []   # level, title, body page (1-based)

    # -- page handling ---------------------------------------------------
    def flush(self) -> None:
        if self.ops:
            self.pages.append(self.ops)
        self.ops = []
        self.y = PAGE_H - M_T

    def _room(self, needed: float) -> None:
        if self.y - needed < M_B:
            self.flush()

    # -- primitives ------------------------------------------------------
    def line_of_text(self, text: str, size=9.6, font="F1", x=M_L, gray=0.16, lead=None) -> None:
        lead = lead or size * 1.35
        self._room(lead)
        self.ops.append(
            f"{gray} g BT /{font} {size:.1f} Tf 1 0 0 1 {x:.1f} {self.y:.1f} Tm ({esc(text)}) Tj ET"
        )
        self.y -= lead

    def rule(self, gray=0.78, pad=4.0, width=BODY_W) -> None:
        self._room(pad + 2)
        self.y -= pad
        self.ops.append(f"0.7 w {gray} G {M_L:.1f} {self.y:.1f} m {M_L + width:.1f} {self.y:.1f} l S")
        self.y -= pad

    def space(self, height: float) -> None:
        self._room(height)
        self.y -= height

    # -- blocks ----------------------------------------------------------
    def heading(self, level: int, title: str) -> None:
        sizes = {1: 16.5, 2: 12.4, 3: 10.4}
        if level == 1:
            if self.ops:
                self.flush()
            self.sections.append((level, title, len(self.pages) + 1))
        else:
            self._room(46)
            self.space(7 if level == 2 else 5)
        self.line_of_text(title, size=sizes[level], font="F2", gray=0.08,
                          lead=sizes[level] * (1.5 if level == 1 else 1.4))
        if level == 1:
            self.rule(gray=0.6, pad=2)
            self.space(4)

    def para(self, text: str, size=9.6, font="F1", indent=0.0, gray=0.16) -> None:
        for line in wrap(text, size, font, BODY_W - indent):
            self.line_of_text(line, size=size, font=font, x=M_L + indent, gray=gray)
        self.space(2.5)

    def bullet(self, text: str, sub=False) -> None:
        indent = 22.0 if sub else 10.0
        marker = "-" if not sub else "."
        lines = wrap(text, 9.6, "F1", BODY_W - indent - 10)
        self.line_of_text(f"{marker}  {lines[0]}", x=M_L + indent)
        for extra in lines[1:]:
            self.line_of_text(extra, x=M_L + indent + 12)

    def code(self, text: str) -> None:
        self.line_of_text(text, size=8.6, font="F3", x=M_L + 10, gray=0.30)

    def table(self, rows: list[list[str]], widths: list[float]) -> None:
        cols = [BODY_W * w for w in widths]
        xs, x = [], M_L
        for width in cols:
            xs.append(x)
            x += width
        for index, row in enumerate(rows):
            font = "F2" if index == 0 else "F1"
            size = 8.8
            cells = [wrap(cell, size, font, cols[i] - 8) for i, cell in enumerate(row)]
            height = max(len(cell) for cell in cells) * (size * 1.3) + 3
            self._room(height + 4)
            top = self.y
            for i, cell in enumerate(cells):
                self.y = top
                for line in cell:
                    self.ops.append(
                        f"{0.08 if index == 0 else 0.2} g BT /{font} {size:.1f} Tf 1 0 0 1 "
                        f"{xs[i]:.1f} {self.y:.1f} Tm ({esc(line)}) Tj ET"
                    )
                    self.y -= size * 1.3
            self.y = top - height
            if index == 0:
                self.ops.append(f"0.5 w 0.75 G {M_L:.1f} {self.y + 4:.1f} m {M_L + BODY_W:.1f} {self.y + 4:.1f} l S")
        self.space(6)


def render(doc: Doc, markup: str) -> None:
    """Render the simple markup used for the handbook body."""
    table_rows: list[list[str]] = []
    table_widths: list[float] = []

    def flush_table() -> None:
        nonlocal table_rows
        if table_rows:
            doc.table(table_rows, table_widths or [1 / len(table_rows[0])] * len(table_rows[0]))
            table_rows = []

    for raw in markup.splitlines():
        line = raw.rstrip()
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            table_rows.append(cells)
            continue
        flush_table()
        if not line.strip():
            doc.space(4)
        elif line.startswith("#W "):                      # column widths for the next table
            table_widths = [float(v) for v in line[3:].split()]
        elif line.startswith("#1 "):
            doc.heading(1, line[3:])
        elif line.startswith("#2 "):
            doc.heading(2, line[3:])
        elif line.startswith("#3 "):
            doc.heading(3, line[3:])
        elif line.startswith("-- "):
            doc.bullet(line[3:], sub=True)
        elif line.startswith("- "):
            doc.bullet(line[2:])
        elif line.startswith("> "):
            doc.code(line[2:])
        elif line.startswith("! "):
            doc.para(line[2:], font="F4", gray=0.25)
        else:
            doc.para(line)
    flush_table()
    doc.flush()


def cover_page(title: str, subtitle: str, lines: list[str]) -> list[str]:
    ops: list[str] = []
    y = PAGE_H - 250
    ops.append(f"0.06 g BT /F2 27 Tf 1 0 0 1 {M_L} {y} Tm ({esc(title)}) Tj ET")
    y -= 30
    ops.append(f"0.30 g BT /F1 13 Tf 1 0 0 1 {M_L} {y} Tm ({esc(subtitle)}) Tj ET")
    y -= 26
    ops.append(f"0.8 w 0.65 G {M_L} {y} m {M_L + BODY_W} {y} l S")
    y -= 28
    for line in lines:
        ops.append(f"0.22 g BT /F1 10.2 Tf 1 0 0 1 {M_L} {y} Tm ({esc(line)}) Tj ET")
        y -= 16
    return ops


def toc_pages(sections: list[tuple[int, str, int]], offset: int) -> list[list[str]]:
    doc = Doc()
    doc.heading(1, "Contents")
    for _, title, page in sections:
        dots = "." * max(3, int((BODY_W - text_width(title, 9.6, "F1") - 30) / (9.6 * 0.505)))
        doc.line_of_text(f"{title}  {dots}  {page + offset}", size=9.6)
    doc.flush()
    return doc.pages


def add_footers(pages: list[list[str]], label: str) -> None:
    total = len(pages)
    for index, ops in enumerate(pages, start=1):
        if index == 1:
            continue
        text = f"{label}   |   Page {index} of {total}"
        ops.append(f"0.55 g BT /F1 7.8 Tf 1 0 0 1 {M_L:.1f} {M_B - 18:.1f} Tm ({esc(text)}) Tj ET")


def build_pdf(pages: list[list[str]], path: Path, title: str) -> None:
    objects: list[bytes] = [b"", b""]          # 1 = catalog, 2 = page tree

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font_ids = {key: add(f"<< /Type /Font /Subtype /Type1 /BaseFont /{name} "
                         f"/Encoding /WinAnsiEncoding >>".encode("latin-1"))
                for key, name in FONTS.items()}
    resources = "<< /Font << " + " ".join(f"/{k} {v} 0 R" for k, v in font_ids.items()) + " >> >>"

    kids = []
    for ops in pages:
        stream = zlib.compress("\n".join(ops).encode("latin-1"), 9)
        content_id = add(b"<< /Length " + str(len(stream)).encode() +
                         b" /Filter /FlateDecode >>\nstream\n" + stream + b"\nendstream")
        kids.append(add(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:.2f} {PAGE_H:.2f}] "
                        f"/Resources {resources} /Contents {content_id} 0 R >>".encode("latin-1")))
    info_id = add(f"<< /Title ({esc(title)}) /Producer (ECR Assistant handbook builder) "
                  f"/CreationDate (D:{date.today():%Y%m%d}000000Z) >>".encode("latin-1"))

    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = (f"<< /Type /Pages /Count {len(kids)} /Kids "
                  f"[{' '.join(f'{k} 0 R' for k in kids)}] >>").encode("latin-1")

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("latin-1")
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info_id} 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n").encode("latin-1")
    path.write_bytes(bytes(out))


ROOT = Path(r"C:\Users\aatmakur\Documents\ecr_assistant_ui")

CODE_SIZE = 7.2
CODE_LEAD = 8.7
CODE_CHARS = int((BODY_W - 26) / (CODE_SIZE * WIDTH_FACTOR["F3"]))


def source_files() -> list[tuple[str, Path]]:
    """Every source file, in reading order."""
    groups: list[tuple[str, list[str]]] = [
        ("Backend - entry point and configuration",
         ["backend/app/main.py", "backend/app/config.py", "backend/app/database.py",
          "backend/app/logging.py", "backend/app/dependencies.py", "backend/app/prompts.py"]),
        ("Backend - CSV data store", ["backend/app/data/*.py"]),
        ("Backend - models (one per CSV table)", ["backend/app/models/*.py"]),
        ("Backend - agent state and orchestration",
         ["backend/app/agents/state.py", "backend/app/agents/orchestrator.py",
          "backend/app/agents/runtime.py", "backend/app/agents/nodes/agents.py",
          "backend/app/agents/nodes/steps.py"]),
        ("Backend - agent steps and parts", ["backend/app/agents/nodes/*.py"]),
        ("Backend - agent tools", ["backend/app/agents/tools/*.py"]),
        ("Backend - services (engines, retrieval, reporting)", ["backend/app/services/*.py"]),
        ("Backend - LLM providers", ["backend/app/llm/*.py"]),
        ("Backend - vector store", ["backend/app/vectorstore/*.py"]),
        ("Backend - dependency graph", ["backend/app/graph/*.py"]),
        ("Backend - repositories", ["backend/app/repositories/*.py"]),
        ("Backend - schemas", ["backend/app/schemas/*.py"]),
        ("Backend - API routes", ["backend/app/api/*.py", "backend/app/api/routes/*.py"]),
        ("Backend - source system integrations", ["backend/app/integrations/*.py"]),
        ("Backend - sample repository parsed by the code analyzer",
         ["backend/app/seed/__main__.py", "backend/app/seed/sample_repo/*/*.py"]),
        ("Backend - tests", ["backend/app/tests/*.py", "backend/app/tests/*/*.py"]),
        ("Frontend - application", ["frontend/src/*.js", "frontend/src/*.css"]),
        ("Frontend - pages", ["frontend/src/pages/*.jsx"]),
        ("Frontend - components", ["frontend/src/components/agents/*.jsx",
                                   "frontend/src/components/common/*.jsx",
                                   "frontend/src/components/layout/*.jsx"]),
        ("Frontend - context, services, theme",
         ["frontend/src/context/*.jsx", "frontend/src/services/*.js", "frontend/src/theme/*.js",
          "frontend/src/lib/*.js", "frontend/src/hooks/*.js"]),
        ("Frontend - shadcn/ui primitives", ["frontend/src/components/ui/*.jsx"]),
        ("Project configuration",
         ["backend/requirements.txt", "backend/pytest.ini", "backend/Dockerfile",
          "docker-compose.yml", "Makefile", ".env.example", "frontend/package.json",
          "frontend/craco.config.js", "frontend/tailwind.config.js"]),
    ]
    seen: set[Path] = set()
    out: list[tuple[str, Path]] = []
    for group, patterns in groups:
        for pattern in patterns:
            matches = sorted(ROOT.glob(pattern)) if "*" in pattern else [ROOT / pattern]
            for path in matches:
                if not path.is_file() or path in seen or "__pycache__" in str(path):
                    continue
                seen.add(path)
                out.append((group, path))
    return out


def code_block(doc: Doc, path: Path) -> int:
    """Print one file with line numbers; long lines wrap with a continuation marker."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    for number, raw in enumerate(lines, start=1):
        text = clean(raw.replace("\t", "    ").rstrip())
        chunks = [text[i:i + CODE_CHARS] for i in range(0, len(text), CODE_CHARS)] or [""]
        for index, chunk in enumerate(chunks):
            prefix = f"{number:>4} " if index == 0 else "   + "
            doc._room(CODE_LEAD)
            doc.ops.append(
                f"0.55 g BT /F3 {CODE_SIZE} Tf 1 0 0 1 {M_L:.1f} {doc.y:.1f} Tm ({esc(prefix)}) Tj ET"
                f" 0.13 g BT /F3 {CODE_SIZE} Tf 1 0 0 1 {M_L + 26:.1f} {doc.y:.1f} Tm ({esc(chunk)}) Tj ET"
            )
            doc.y -= CODE_LEAD
    return len(lines)


def data_samples(doc: Doc) -> None:
    doc.heading(2, "Data file samples (header and first rows)")
    doc.para("The full data is in backend/data. Each file below shows its header row and the first "
             "two data rows, so the column layout and value format are visible without reproducing "
             "thousands of rows.")
    for csv_path in sorted((ROOT / "backend" / "data").glob("*.csv")):
        rows = csv_path.read_text(encoding="utf-8", errors="replace").splitlines()
        total = max(0, len(rows) - 1)
        doc.heading(3, f"{csv_path.name}  ({total} rows)")
        for raw in rows[:3]:
            text = clean(raw)[:600]
            for i in range(0, len(text), CODE_CHARS):
                doc.line_of_text(text[i:i + CODE_CHARS], size=CODE_SIZE, font="F3",
                                 x=M_L + 8, gray=0.3, lead=CODE_LEAD)
        doc.space(4)


def source_appendix(doc: Doc) -> None:
    doc.heading(1, "26. Complete source code")
    doc.para("Every source file of the project follows, grouped by area and shown with line "
             "numbers. A line too long for the page continues on the next line, marked with a plus "
             "sign. Generated files, dependencies, build output and the data files themselves are "
             "not included; data samples are in the section after the code.")
    current_group = ""
    total_files = total_lines = 0
    for group, path in source_files():
        if group != current_group:
            current_group = group
            doc.heading(2, group)
        relative = path.relative_to(ROOT).as_posix()
        doc.space(3)
        doc.line_of_text(relative, size=9.4, font="F2", gray=0.08)
        doc.rule(gray=0.85, pad=2)
        count = code_block(doc, path)
        total_files += 1
        total_lines += count
        doc.space(6)
    doc.heading(2, "Source totals")
    doc.para(f"{total_files} files, {total_lines:,} lines of code.")
    data_samples(doc)


def main() -> None:
    from handbook_content import CONTENT, TITLE, SUBTITLE, COVER_LINES

    body = Doc()
    render(body, CONTENT)
    source_appendix(body)
    body.flush()

    guess = 1
    for _ in range(4):
        toc = toc_pages(body.sections, offset=1 + guess)
        if len(toc) == guess:
            break
        guess = len(toc)

    pages = [cover_page(TITLE, SUBTITLE, COVER_LINES)] + toc + body.pages
    add_footers(pages, "ECR Assistant - Project Handbook")
    build_pdf(pages, OUT, TITLE)
    print(f"wrote {OUT}  ({OUT.stat().st_size / 1024:.0f} KB, {len(pages)} pages)")


if __name__ == "__main__":
    main()
