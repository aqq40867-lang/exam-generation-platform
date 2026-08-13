"""
LaTeX template + PDF compilation for exported exam papers (组卷导出).

This module is deliberately independent of NiceGUI/the UI layer: given a
plain description of an exam (name, description, target total marks) and
an ordered list of questions (each with the marks it is worth *in this
exam*, which may differ from the question's own default "Marks" value in
the question bank), it builds a self-contained .tex document and can
compile that document to a PDF using whatever LaTeX engine is available
on the machine (pdflatex / xelatex / tectonic).

Only the `geometry` package is required beyond a bare `article` class, so
the template should compile on essentially any TeX Live / MiKTeX
installation without extra package dependencies.
"""

import base64
import os
import shutil
import subprocess
import tempfile
import unicodedata


class LatexCompileError(RuntimeError):
    """Raised when no LaTeX engine is available, or compilation fails."""
    pass


# ---------------------------------------------------------------------------
# Escaping
# ---------------------------------------------------------------------------

_LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "<": r"\textless{}",
    ">": r"\textgreater{}",
}

# Unicode symbols that question/answer/table text commonly contains (e.g.
# "MST <- {}" traces, set notation, comparisons) but that plain pdflatex
# with `inputenc[utf8]` cannot typeset directly -- pdflatex only knows the
# handful of accented Latin characters inputenc declares, so anything else
# (mathematical symbols, smart punctuation, Greek letters, ...) needs to be
# swapped for an equivalent LaTeX command instead. Each replacement that
# needs math mode is wrapped in its own `$...$` so it works whether it's
# embedded in running text or inside a table cell. `amssymb` (already
# loaded in _HEADER) covers all the math commands used below.
_UNICODE_SYMBOLS = {
    "∅": r"$\emptyset$",
    "≤": r"$\leq$",
    "≥": r"$\geq$",
    "≠": r"$\neq$",
    "≈": r"$\approx$",
    "→": r"$\rightarrow$",
    "←": r"$\leftarrow$",
    "↔": r"$\leftrightarrow$",
    "⇒": r"$\Rightarrow$",
    "∞": r"$\infty$",
    "±": r"$\pm$",
    "×": r"$\times$",
    "÷": r"$\div$",
    "°": r"$^{\circ}$",
    "∈": r"$\in$",
    "∉": r"$\notin$",
    "⊆": r"$\subseteq$",
    "⊂": r"$\subset$",
    "∪": r"$\cup$",
    "∩": r"$\cap$",
    "∀": r"$\forall$",
    "∃": r"$\exists$",
    "∑": r"$\sum$",
    "∏": r"$\prod$",
    "√": r"$\sqrt{}$",
    "∂": r"$\partial$",
    "∇": r"$\nabla$",
    "⌈": r"$\lceil$",
    "⌉": r"$\rceil$",
    "⌊": r"$\lfloor$",
    "⌋": r"$\rfloor$",
    "∴": r"$\therefore$",
    "∵": r"$\because$",
    "⊥": r"$\bot$",
    "∧": r"$\wedge$",
    "∨": r"$\vee$",
    "¬": r"$\neg$",
    "⇔": r"$\Leftrightarrow$",
    "↦": r"$\mapsto$",
    "∘": r"$\circ$",
    "⌀": r"$\emptyset$",
    "∖": r"$\setminus$",
    "⊇": r"$\supseteq$",
    "⊃": r"$\supset$",
    "≡": r"$\equiv$",
    "≪": r"$\ll$",
    "≫": r"$\gg$",
    "−": "-",
    "⋅": r"$\cdot$",
    "·": r"$\cdot$",
    "′": r"$'$",
    "″": r"$''$",
    "ℓ": r"$\ell$",
    "ℝ": r"$\mathbb{R}$",
    "ℕ": r"$\mathbb{N}$",
    "ℤ": r"$\mathbb{Z}$",
    "ℚ": r"$\mathbb{Q}$",
    "ℂ": r"$\mathbb{C}$",
    "Δ": r"$\Delta$",
    "α": r"$\alpha$",
    "β": r"$\beta$",
    "γ": r"$\gamma$",
    "δ": r"$\delta$",
    "ε": r"$\varepsilon$",
    "θ": r"$\theta$",
    "κ": r"$\kappa$",
    "λ": r"$\lambda$",
    "μ": r"$\mu$",
    "ν": r"$\nu$",
    "π": r"$\pi$",
    "ρ": r"$\rho$",
    "σ": r"$\sigma$",
    "τ": r"$\tau$",
    "φ": r"$\varphi$",
    "χ": r"$\chi$",
    "ψ": r"$\psi$",
    "ω": r"$\omega$",
    "Γ": r"$\Gamma$",
    "Θ": r"$\Theta$",
    "Λ": r"$\Lambda$",
    "Π": r"$\Pi$",
    "Σ": r"$\Sigma$",
    "Φ": r"$\Phi$",
    "Ψ": r"$\Psi$",
    "Ω": r"$\Omega$",
    "•": r"$\bullet$",
    "‣": r"$\bullet$",
    "…": r"\ldots{}",
    "–": "--",
    "—": "---",
    "‘": "`",
    "’": "'",
    "“": "``",
    "”": "''",
}


def _fallback_symbol(ch: str) -> str:
    """Best-effort rendering for a character with no explicit mapping.

    Teachers can paste arbitrary Unicode into question/answer/table text,
    so `_UNICODE_SYMBOLS` above can never be a complete list -- there will
    always be some symbol (an obscure math operator, an emoji, a currency
    sign, ...) it hasn't seen yet. Previously that meant pdflatex's
    "Unicode character ... not set up for use with LaTeX" fatal error,
    which blocks exporting the *entire* exam over one stray character
    buried in one question.

    Latin-1 Supplement characters (U+0080-U+00FF: accented Latin letters
    like e/n/u, plus a handful of symbols such as micro-sign) are passed
    through untouched -- pdflatex's `inputenc[utf8]` renders those
    natively without any extra package. Anything above that range and not
    already in `_UNICODE_SYMBOLS` is replaced with a bracketed,
    human-readable placeholder built from the character's Unicode name
    (e.g. "[RIGHT DOUBLE QUOTATION MARK]"), so the document still
    compiles and the placeholder makes it obvious in the printed output
    that a character needs fixing at the source.

    Args:
        ch: A single character with `ord(ch) > 127`.

    Returns:
        Either `ch` itself (Latin-1 Supplement) or an escaped bracketed
        placeholder describing it.
    """
    if 0x80 <= ord(ch) <= 0xFF:
        return ch
    try:
        name = unicodedata.name(ch)
    except ValueError:
        name = f"U+{ord(ch):04X}"
    return "".join(_LATEX_SPECIAL_CHARS.get(c, c) for c in f"[{name}]")


def escape_latex(text) -> str:
    """Escape a plain string so it's safe to drop into LaTeX source.

    Args:
        text: Value to escape. Converted with `str()`; `None` becomes an
            empty string.

    Returns:
        The input with LaTeX special characters (backslash, &, %, $, #,
        _, {, }, ~, ^, <, >) replaced by their escaped equivalents,
        common Unicode math/typography symbols (empty set, comparisons,
        arrows, Greek letters, smart quotes, ...) replaced by LaTeX
        commands, and any other non-Latin-1 character replaced by a
        readable placeholder -- see `_fallback_symbol` -- so a single
        unanticipated character can never fail the whole PDF compile.
    """
    if text is None:
        return ""
    text = str(text)
    out = []
    for ch in text:
        if ch in _LATEX_SPECIAL_CHARS:
            out.append(_LATEX_SPECIAL_CHARS[ch])
        elif ch in _UNICODE_SYMBOLS:
            out.append(_UNICODE_SYMBOLS[ch])
        elif ord(ch) > 127:
            out.append(_fallback_symbol(ch))
        else:
            out.append(ch)
    return "".join(out)


def _paragraphs(text: str) -> str:
    """Convert blank-line-separated plain text into LaTeX paragraphs.

    Each block of text is escaped first; single newlines within a block
    become LaTeX line breaks rather than starting a new paragraph.

    Note the `\\{}` (not just `\\`): a bare `\\` line-break command takes
    an optional `[<length>]` argument for extra vertical space, so if the
    very next character happens to be a literal "[" -- e.g. a line
    starting "[Given the graph below]...", or a bulleted line whose "*"
    was rendered as the "[BULLET]" fallback placeholder -- LaTeX tries to
    parse "Given the graph below]" (or "BULLET]") as a length and dies
    with "Missing number, treated as zero." The empty group after `\\`
    blocks that lookup, so a following "[" is always read as plain text.

    Args:
        text: Plain text, with paragraphs separated by a blank line.

    Returns:
        The escaped text, reassembled as LaTeX paragraphs.
    """
    escaped = escape_latex(text)
    blocks = [block.strip() for block in escaped.split("\n\n") if block.strip()]
    if not blocks:
        return ""
    return "\n\n".join(block.replace("\n", r" \\{} ") for block in blocks)


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

_HEADER = r"""\documentclass[12pt]{article}
\usepackage[a4paper, margin=2.5cm]{geometry}
\usepackage[utf8]{inputenc}
\usepackage{amssymb}
\usepackage[table]{xcolor}
\usepackage{framed}
\usepackage{longtable}
\usepackage{array}
\usepackage{graphicx}
\definecolor{shadecolor}{gray}{0.92}
\setlength{\parindent}{0pt}
\setlength{\parskip}{6pt}
\setlength{\tabcolsep}{8pt}

\begin{document}

\begin{center}
    {\LARGE \textbf{%(name)s}}\\[0.3cm]
    %(subtitle)s
    \vspace{0.15cm}

    \textbf{Total Marks: %(total)s}
\end{center}

\vspace{0.4cm}
\hrule
\vspace{0.6cm}

"""

_FOOTER = r"""
\end{document}
"""


# Layout rule (agreed with the user): each major question's sub-questions
# are limited to at most 2 per printed page, so a page never carries more
# than a question's own header/description plus 2 sub-questions.
_MAX_SUB_QUESTIONS_PER_PAGE = 2

# Printed under every reserved answer-writing area on the "official" paper
# (matches the wording on the reference Loughborough exam paper): lets a
# student flag that they've kept writing on one of the blank continuation
# pages at the end of the booklet (see _render_continuation_pages) instead
# of running out of room. Doesn't apply to "example"/"solutions" exports --
# those aren't printed exam booklets a student writes and hands in, so
# there's no "continuation pages at the back" to point to.
_TICK_LINE = (
    r"\noindent\textit{Tick here if you continue at the end of the booklet:}"
    r"\quad $\Box$\\"
)

# The three export modes (see build_latex):
#   official  -- the real exam paper, printed and handed to students in the
#                exam hall. Blank answer space, the tick line above, and
#                blank continuation pages at the end.
#   example   -- a practice paper for revision, downloaded as a document
#                (not printed/marked), so no tick line and no continuation
#                pages. Still has blank answer space so a student can
#                attempt it before checking the paired "solutions" export.
#   solutions -- the same questions as "example", but with the standard
#                answer shown inline in a shaded box under each question
#                instead of blank space, so a student can self-mark after
#                attempting the "example" version.
_MODES = ("official", "example", "solutions")


def _render_solution_block(answer_text) -> str:
    """Render a shaded "Solution:" box for the "solutions" export mode.

    The box is shown inline in place of the blank answer space used by
    the "official"/"example" export modes.

    Args:
        answer_text: The question's or part's recorded standard answer.
            May be empty or `None`, in which case a placeholder note is
            rendered instead.

    Returns:
        LaTeX source for the shaded solution box.
    """
    if answer_text and str(answer_text).strip():
        body = _paragraphs(answer_text)
    else:
        body = escape_latex("(No standard answer recorded for this question.)")
    return (
        r"\begin{shaded}" + "\n"
        r"\textbf{Solution:}\par\smallskip" + "\n"
        + body + "\n"
        r"\end{shaded}"
    )


def _render_table_spec(spec: dict, *, stretched: bool) -> str:
    """Render a bordered, wrapped LaTeX table from a resolved table spec.

    Used for step-by-step / tracing questions -- see database.py's
    replace_question_parts docstring for the "Table spec" shape this
    reads (the problem table, what the student sees) -- there's no
    per-column masking here, cells are printed exactly as given
    (including blank, for "the student writes here").

    Columns are wrapped `p{width}` cells (evenly splitting the page's
    text width, `array`'s `\\raggedright\\arraybackslash` keeps them
    left-aligned) rather than plain unwrapped `l` columns -- a plain `l`
    column never breaks a long header or cell onto a second line, so a
    single full-sentence cell used to silently push the whole table past
    the page's right margin instead of wrapping. The header row gets a
    light shaded background (`colortbl`, via `xcolor`'s `table` option)
    so it reads as a header at a glance instead of just being bold text
    on the same white background as the data rows.

    Row height is stretched when `stretched` is True so there's actually
    room to write by hand in a blank cell -- used outside "solutions"
    mode, where the student needs room to fill the table in; compact in
    "solutions" mode, where the table is just shown for reference and
    nothing needs to be written by hand.

    Args:
        spec: A {"given_columns", "answer_columns", "rows"} dict.
        stretched: Whether to reserve extra row height for handwriting.

    Returns:
        LaTeX source for the table, or an escaped placeholder message if
        the spec has no columns or rows configured yet.
    """
    given_cols = [str(c) for c in (spec.get("given_columns") or [])]
    answer_cols = [str(c) for c in (spec.get("answer_columns") or [])]
    rows = spec.get("rows") or []
    headers = given_cols + answer_cols
    n = len(headers)

    if n == 0 or not rows:
        return escape_latex("(This table has not been configured yet.)")

    # \textwidth for this document is ~16cm (a4paper, 2.5cm margins on
    # both sides -- see the `geometry` package options in _HEADER). Split
    # it evenly across columns, minus a small per-column allowance for
    # cell padding/rule width so an n-column table lands at (not just
    # under) \linewidth instead of a hair over it. Floored at 1.6cm so a
    # table with many columns stays readable rather than collapsing to
    # sliver-thin cells -- it may then run slightly past \linewidth, but
    # that's a graceful degrade for an unusually wide table rather than
    # the normal case.
    col_width_cm = max(1.6, 16.0 / n - 0.35)
    col_type = r">{\raggedright\arraybackslash}p{%.2fcm}" % col_width_cm
    col_spec = "|" + "|".join([col_type] * n) + "|"
    header_row = (
        r"\rowcolor{gray!15}"
        + " & ".join(r"\textbf{%s}" % escape_latex(h) for h in headers)
        + r" \\ \hline"
    )

    # A plain `tabular` is an atomic box to LaTeX's page breaker: if it
    # doesn't fit in the space left on the current page, the *whole* table
    # (not a row) moves to the next page -- so a short table is already
    # safe. But a table taller than one whole page (a long step-by-step
    # trace, especially with the extra row height below for handwriting
    # room) has nowhere to go and silently overflows/gets clipped past the
    # bottom margin, which is its own version of "the table got cut off".
    # `longtable` is the standard fix: unlike `tabular`, it's allowed to
    # break across a page boundary between rows (never mid-row), repeating
    # the header on each new page so it's still readable.
    lines = []
    lines.append(r"\renewcommand{\arraystretch}{%s}" % ("2.4" if stretched else "1.3"))
    lines.append(r"\begingroup\centering")
    lines.append(r"\begin{longtable}{%s}" % col_spec)
    lines.append(r"\hline")
    lines.append(header_row)
    lines.append(r"\endfirsthead")
    lines.append(r"\hline")
    lines.append(header_row)
    lines.append(r"\multicolumn{%d}{r}{\small\textit{(continued from previous page)}}\\[-2pt]" % n)
    lines.append(r"\endhead")
    lines.append(r"\hline")
    lines.append(
        r"\multicolumn{%d}{r}{\small\textit{(continued on next page)}}\\" % n
    )
    lines.append(r"\endfoot")
    lines.append(r"\hline")
    lines.append(r"\endlastfoot")
    for row in rows:
        cells = [str(c) for c in row] + [""] * max(0, n - len(row))
        rendered = [escape_latex(cells[i]) for i in range(n)]
        lines.append(" & ".join(rendered) + r" \\ \hline")
    lines.append(r"\end{longtable}")
    lines.append(r"\endgroup")
    lines.append(r"\renewcommand{\arraystretch}{1}")
    return "\n".join(lines)


def _render_table_block(block: dict, *, mode: str) -> str:
    """Render one "table"-type content block's problem table, on every export mode.

    A table block is just its rows -- the same problem table (what the
    student sees, blank cells and all) on official/example/solutions
    alike; its standard answer is free text, rendered separately via the
    owning sub-question's normal solution box (_render_solution_block),
    exactly like a text-only sub-question's, rather than as a second
    mirrored table here. Row height is only stretched (extra room for
    handwriting) outside "solutions" mode -- nothing needs to be written
    by hand there.

    Args:
        block: One "table"-type content block dict, carrying "table_spec".
        mode: One of _MODES -- only affects row height/stretching here.

    Returns:
        LaTeX source for the table, ready to be appended as its own
        block of lines.
    """
    spec = block.get("table_spec") or {}
    return _render_table_spec(spec, stretched=(mode != "solutions"))


_ROMAN_VALUES = [
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
    (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
    (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
]


def _roman_for_index(index: int) -> str:
    """Converts a zero-based position into a lower-case Roman numeral label.

    E.g. 0 -> "i", 1 -> "ii", 2 -> "iii", 8 -> "ix", etc. Used as a
    fallback for a "Sub parts" entry that's somehow missing its own
    "Label" -- create_question.py always sets one, so this only matters
    for hand-edited/legacy data.

    Args:
        index: The 0-based position of the sub-part.

    Returns:
        The Roman numeral label for that position.
    """
    n = index + 1
    result = []
    for value, symbol in _ROMAN_VALUES:
        while n >= value:
            result.append(symbol)
            n -= value
    return "".join(result)


def _sniff_image_extension(data: bytes) -> str:
    """Guess a raster image's real format from its bytes.

    Sniffing avoids trusting whatever extension the original upload
    happened to have -- pdflatex's \\includegraphics picks its loader by
    file extension, so embedding JPEG bytes under a ".png" name (or vice
    versa) fails to compile.

    Args:
        data: Raw image bytes.

    Returns:
        A lowercase extension without the leading dot ("png" or "jpg").
        Falls back to "png" for anything unrecognised; \\includegraphics
        will then fail loudly (a normal LatexCompileError) rather than
        silently embedding garbage.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:2] == b"\xff\xd8":
        return "jpg"
    return "png"


def _collect_image_assets(questions_with_marks: list):
    """Decode every question's and part's base64 image data exactly once.

    An image may sit in a question's own "Main content blocks" (its
    overall problem statement), or be attached to any part regardless of
    "Part type" -- a "text" or "table" sub-problem can carry one
    alongside its own content, and legacy standalone "image"-type parts
    still work too. Each decoded image is assigned a short
    filesystem-safe filename.

    Args:
        questions_with_marks: List of (question_dict, marks, parts_list)
            tuples, as passed to build_latex().

    Returns:
        A tuple (assets, filenames): `assets` is {filename: raw_bytes},
        handed to compile_latex_to_pdf() to write into the compile
        directory before running the LaTeX engine. `filenames` maps both
        id(part) -> filename (for a legacy standalone "image"-type part,
        see _render_image_part()) and id(block) -> filename (for an
        "image" content block, see _render_image_block()) -- keyed by
        Python object identity rather than a database id, since a
        not-yet-saved preview's parts/blocks don't have one at all.
    """
    assets = {}
    filenames = {}
    counter = 0

    def _register(raw_b64, key) -> None:
        nonlocal counter
        if not raw_b64:
            return
        try:
            data = base64.b64decode(raw_b64)
        except (ValueError, TypeError):
            return
        counter += 1
        filename = f"img_{counter}.{_sniff_image_extension(data)}"
        assets[filename] = data
        filenames[key] = filename

    for question, _marks, parts in questions_with_marks:
        for block in (question.get("Main content blocks") or []):
            if block.get("type") == "image":
                _register(block.get("image_data"), id(block))
        for part in parts:
            _register(part.get("Image data"), id(part))
            for block in (part.get("Content blocks") or []):
                if block.get("type") == "image":
                    _register(block.get("image_data"), id(block))
            for sub_part in (part.get("Sub parts") or []):
                for block in (sub_part.get("Content blocks") or []):
                    if block.get("type") == "image":
                        _register(block.get("image_data"), id(block))
    return assets, filenames


def _render_material_part(part: dict) -> str:
    """Render a non-gradable block of reading material/stimulus text.

    The block is shown inline wherever it sits in the component order
    (unlike the parent question's single "Main question" field, which is
    always pinned to the very top).

    Args:
        part: The question part dict, expected to hold a "Description".

    Returns:
        LaTeX source for the material block, or an escaped placeholder
        message if the part has no description text.
    """
    body = part.get("Description")
    if not body or not str(body).strip():
        return escape_latex("(This material block is empty.)")
    return _paragraphs(body)


def _render_image_part(part: dict, image_filenames: dict, *, caption=None) -> str:
    """Render an embedded image, centered on the page.

    Args:
        part: The question part dict carrying "Image data".
        image_filenames: The id(part) -> filename map built by
            _collect_image_assets(). The actual file must already have
            been written into the compile directory by the time this is
            used.
        caption: Optional caption text shown underneath the image. If
            omitted (None), falls back to the part's own "Description" --
            correct for a legacy standalone "image"-type part, where
            "Description" is only ever used as this caption. When an
            image is attached to a "text"/"table" sub-problem instead,
            "Description" is that sub-problem's own text (already
            rendered above, as the item itself) -- callers pass an empty
            string explicitly there to suppress a duplicate caption.

    Returns:
        LaTeX source for the centered image, or an escaped placeholder
        message if no matching file was found.
    """
    filename = image_filenames.get(id(part))
    if not filename:
        return escape_latex("(This image could not be loaded.)")
    lines = [
        r"\begin{center}",
        r"\includegraphics[width=0.8\linewidth,height=0.5\textheight,keepaspectratio]{%s}" % filename,
    ]
    if caption is None:
        caption = part.get("Description")
    if caption and str(caption).strip():
        lines.append(r"\\[4pt]")
        lines.append(r"{\small\itshape %s}" % escape_latex(caption))
    lines.append(r"\end{center}")
    return "\n".join(lines)


def _render_image_block(block: dict, image_filenames: dict) -> str:
    """Render one "image"-type content block, centered, with no caption.

    The block-based sibling of _render_image_part() above -- same visual
    output, but reads a content block's own lowercase keys
    ("image_data"/"image_filename") instead of a part's DB-column-cased
    ones, and is looked up in `image_filenames` by id(block) rather than
    id(part) (a part can now carry more than one image block). Never
    shows a caption: unlike a legacy standalone "image"-type part (where
    "Description" doubles as the caption), a block sits inline among a
    sub-question's other blocks and any caption-like text is just another
    text block placed next to it.

    Args:
        block: A content block dict with "type" == "image".
        image_filenames: The id(...) -> filename map built by
            _collect_image_assets().

    Returns:
        LaTeX source for the centered image, or an escaped placeholder
        message if no matching file was found.
    """
    filename = image_filenames.get(id(block))
    if not filename:
        return escape_latex("(This image could not be loaded.)")
    return "\n".join([
        r"\begin{center}",
        r"\includegraphics[width=0.8\linewidth,height=0.5\textheight,keepaspectratio]{%s}" % filename,
        r"\end{center}",
    ])


def _render_question(
    number: int, question: dict, marks: int, parts: list, mode: str = "official",
    image_filenames: dict = None,
) -> str:
    """Render one full exam question, including all of its parts.

    Renders the question's own text/context, then walks its parts in
    order: material/image stimulus content is rendered inline, and
    lettered sub-questions are rendered inside an itemize list, each with
    reserved blank answer space (or a shaded solution box, in
    "solutions" mode) -- unless a sub-question carries its own "Sub
    parts" (see models.py's QuestionPart.sub_parts), in which case it
    instead renders a nested itemize of (i)/(ii)/(iii)... sub-parts, each
    with its own marks/content/answer handling, and reserves no answer
    space of its own. If the question has no parts, the same blank
    space / solution box is reserved for the question as a whole.

    Args:
        number: The question's 1-based position on the paper, used for
            its "Question N" heading.
        question: The question dict, as stored in the question bank.
        marks: The marks this question is worth on this particular exam,
            which may differ from the question's own default "Marks"
            value.
        parts: The question's ordered list of part dicts (sub-questions,
            material, and image components).
        mode: Export mode -- "official", "example", or "solutions".
            Controls whether blank answer space, tick lines, or inline
            solution boxes are rendered.
        image_filenames: The id(part) -> filename map built by
            _collect_image_assets(), used to resolve "image"-type parts.

    Returns:
        LaTeX source for the whole question, including its trailing
        vertical spacing.
    """
    image_filenames = image_filenames or {}

    lines = []
    lines.append(
        # Guarded with \\{} (see _paragraphs docstring above) since the
        # very next line is the question's own text, which is arbitrary
        # user content and could start with a literal "[".
        r"\noindent\textbf{Question %d} \hfill \textbf{[%d marks]}\\{}"
        % (number, marks)
    )
    lines.append(_paragraphs(question.get("Question", "")))

    # The overall problem statement/stimulus, shown above the lettered
    # sub-problems (if any). "Main content blocks" -- the same ordered
    # text/image/table block shape a sub-problem's own content uses (see
    # models.py's Question.main_content_blocks) -- is the current
    # representation; database.py's get_question()/load_questions()
    # already fall back to synthesizing a single text block from the
    # legacy flat "Main question" field when it's empty, so this is
    # always the right thing to render regardless of how old the row is.
    main_blocks = question.get("Main content blocks") or []
    for block in main_blocks:
        btype = block.get("type")
        lines.append("")
        if btype == "text":
            text = (block.get("text") or "").strip()
            if text:
                lines.append(_paragraphs(text))
        elif btype == "image":
            lines.append(_render_image_block(block, image_filenames))
        elif btype == "table":
            lines.append(_render_table_block(block, mode=mode))

    if parts:
        lines.append("")

        # "material"/"image" components are stimulus content, not lettered
        # sub-questions -- they render as plain content between (rather
        # than inside) the itemize list, since a mid-list "reading
        # material" block that got its own bullet and answer space would
        # be nonsensical. This tracks whether we're currently inside an
        # open itemize, opening/closing it around runs of gradable parts
        # so the list environment never has to contain non-item content.
        in_list = False

        def _open_list():
            nonlocal in_list
            if not in_list:
                lines.append(r"\begin{itemize}")
                in_list = True

        def _close_list():
            nonlocal in_list
            if in_list:
                lines.append(r"\end{itemize}")
                in_list = False

        # Tracks how many sub-questions have been placed on the current
        # page since the last forced page break, so we can enforce the
        # "max 2 sub-questions per page" rule below. Only relevant when
        # blank answer space is actually being reserved (official/example);
        # "solutions" mode doesn't reserve space so pages fill naturally.
        items_since_break = 0

        for idx, part in enumerate(parts):
            is_last = (idx == len(parts) - 1)
            part_type = part.get("Part type") or "text"

            if part_type == "material":
                _close_list()
                lines.append(_render_material_part(part))
                lines.append("")
                continue

            if part_type == "image":
                _close_list()
                lines.append(_render_image_part(part, image_filenames))
                lines.append("")
                continue

            _open_list()
            label = escape_latex(part.get("Label") or "")
            part_marks = part.get("Marks")
            marks_suffix = r" \hfill \textbf{[%d]}" % part_marks if part_marks else ""

            # Sub-problem content is now an ordered list of blocks (text/
            # image/table, in whatever order the teacher arranged them --
            # see models.py's QuestionPart.content_blocks and
            # database.py's get_question_parts()), not the old fixed
            # "description, then image, then table" layout. The first
            # block, *if* it's text, sits inline on the "\item[...]" line
            # itself -- exactly like the old "Description" field did, so a
            # plain text-only sub-problem's LaTeX is byte-for-byte
            # unchanged. Everything else (a non-text first block, or any
            # block after the first) is rendered as its own line(s)
            # underneath, in order.
            blocks = part.get("Content blocks") or []
            has_table_block = any(b.get("type") == "table" for b in blocks)
            first_is_text = bool(blocks) and blocks[0].get("type") == "text"
            item_text = escape_latex(blocks[0].get("text") or "") if first_is_text else ""
            lines.append(r"\item[(%s)] %s%s" % (label, item_text, marks_suffix))

            remaining_blocks = blocks[1:] if first_is_text else blocks
            for block in remaining_blocks:
                btype = block.get("type")
                lines.append("")
                if btype == "text":
                    lines.append(_paragraphs(block.get("text") or ""))
                elif btype == "image":
                    lines.append(_render_image_block(block, image_filenames))
                elif btype == "table":
                    # A table's own rows are its "answer space" -- no
                    # blank \vspace and no "tick here if you continue"
                    # line. The same problem table (what the student
                    # sees) is rendered on every mode; the standard
                    # answer for the whole sub-question is free text,
                    # shown separately below via the normal solution box
                    # (see the has_table_block handling further down),
                    # exactly like a text-only sub-question's.
                    lines.append(_render_table_block(block, mode=mode))

            # A sub-problem broken down further into (i)/(ii)/(iii)... --
            # see models.py's QuestionPart.sub_parts -- renders each
            # sub-part as its own nested \item, with its own marks,
            # content blocks, and answer space/solution/table handling,
            # *instead of* this sub-problem reserving an answer area of
            # its own (its "Marks" is already the sum of its sub-parts',
            # and its "Answer" is unused -- see create_question.py's
            # _build_part_dict). A plain nested itemize is fine here:
            # LaTeX's itemize nests without any extra setup, and every
            # sub-item's own "\item[(i)]" label already overrides
            # whatever bullet style that level would otherwise use.
            sub_parts = part.get("Sub parts") or []
            if sub_parts:
                lines.append("")
                lines.append(r"\begin{itemize}")
                for sub_idx, sub_part in enumerate(sub_parts):
                    is_last_sub_item = is_last and (sub_idx == len(sub_parts) - 1)
                    sub_label = escape_latex(sub_part.get("Label") or _roman_for_index(sub_idx))
                    sub_marks = sub_part.get("Marks")
                    sub_marks_suffix = r" \hfill \textbf{[%d]}" % sub_marks if sub_marks else ""

                    sub_blocks = sub_part.get("Content blocks") or []
                    sub_has_table = any(b.get("type") == "table" for b in sub_blocks)
                    sub_first_is_text = bool(sub_blocks) and sub_blocks[0].get("type") == "text"
                    sub_item_text = (
                        escape_latex(sub_blocks[0].get("text") or "") if sub_first_is_text else ""
                    )
                    lines.append(r"\item[(%s)] %s%s" % (sub_label, sub_item_text, sub_marks_suffix))

                    sub_remaining = sub_blocks[1:] if sub_first_is_text else sub_blocks
                    for block in sub_remaining:
                        btype = block.get("type")
                        lines.append("")
                        if btype == "text":
                            lines.append(_paragraphs(block.get("text") or ""))
                        elif btype == "image":
                            lines.append(_render_image_block(block, image_filenames))
                        elif btype == "table":
                            lines.append(_render_table_block(block, mode=mode))

                    if sub_has_table:
                        if mode == "solutions":
                            lines.append(_render_solution_block(sub_part.get("Answer")))
                        else:
                            lines.append("")
                        continue

                    if mode == "solutions":
                        lines.append(_render_solution_block(sub_part.get("Answer")))
                        continue

                    sub_answer_space = str(sub_part.get("Answer space") or "half").strip().lower()
                    if sub_answer_space == "full":
                        lines.append(r"\newpage")
                        if mode == "official":
                            lines.append(r"\vspace*{\fill}")
                            lines.append(_TICK_LINE)
                            lines.append(r"\newpage")
                        else:
                            lines.append(r"\newpage")
                        items_since_break = 0
                    else:
                        lines.append(r"\vspace{0.4\textheight}")
                        if mode == "official":
                            lines.append(_TICK_LINE)
                        items_since_break += 1
                        if items_since_break >= _MAX_SUB_QUESTIONS_PER_PAGE and not is_last_sub_item:
                            lines.append(r"\newpage")
                            items_since_break = 0
                lines.append(r"\end{itemize}")
                lines.append("")
                continue

            if has_table_block:
                if mode == "solutions":
                    lines.append(_render_solution_block(part.get("Answer")))
                else:
                    lines.append("")
                continue

            if mode == "solutions":
                lines.append(_render_solution_block(part.get("Answer")))
                continue

            # Reserved blank answer area for this sub-question: either
            # roughly half a page of blank space inline, or a whole blank
            # page to itself (forces a page break; the next content starts
            # on the page after that). The "tick here if you continue..."
            # line only applies to the "official" (printed) paper.
            answer_space = str(part.get("Answer space") or "half").strip().lower()
            if answer_space == "full":
                lines.append(r"\newpage")
                if mode == "official":
                    lines.append(r"\vspace*{\fill}")
                    lines.append(_TICK_LINE)
                    lines.append(r"\newpage")
                else:
                    lines.append(r"\newpage")
                items_since_break = 0
            else:
                lines.append(r"\vspace{0.5\textheight}")
                if mode == "official":
                    lines.append(_TICK_LINE)
                items_since_break += 1
                if items_since_break >= _MAX_SUB_QUESTIONS_PER_PAGE and not is_last:
                    lines.append(r"\newpage")
                    items_since_break = 0

        _close_list()
    else:
        # Plain question with no sub-parts.
        lines.append("")
        if mode == "solutions":
            lines.append(_render_solution_block(question.get("Answer")))
        else:
            lines.append(r"\vspace{0.5\textheight}")
            if mode == "official":
                lines.append(_TICK_LINE)

    lines.append("")
    lines.append(r"\vspace{0.8cm}")
    return "\n".join(lines)


def _render_continuation_pages(count: int = 3) -> str:
    """Render blank pages appended to the end of the "official" booklet.

    These give students who ticked "continue at the end of the booklet"
    on a question extra room beyond what was reserved inline. No label
    text -- just blank writing space.

    Args:
        count: Number of blank pages to append.

    Returns:
        LaTeX source for `count` blank pages.
    """
    lines = []
    for _ in range(count):
        lines.append(r"\newpage")
        lines.append(r"\hspace{0pt}")
    return "\n".join(lines)


def build_latex(
    name: str,
    description: str,
    total_marks: int,
    questions_with_marks: list,
    mode: str = "official",
):
    """Build a full .tex document for an exam paper.

    Args:
        name: The exam's title, shown at the top of the paper.
        description: Optional free-text subtitle/description.
        total_marks: The paper's target total marks, shown under the
            title.
        questions_with_marks: List of (question_dict, marks, parts_list)
            tuples, already in the order they should appear on the
            paper.
        mode: One of "official" (the printed exam paper -- blank answer
            space, tick lines, blank continuation pages at the end),
            "example" (a revision/practice paper -- blank answer space
            but no tick lines or continuation pages, since it isn't
            printed and handed in), or "solutions" (the same questions
            as "example" but with each answer shown inline in a shaded
            box instead of blank space, for students to self-mark
            against after attempting "example").

    Returns:
        A tuple (tex_source, assets): `assets` is {filename: raw_bytes}
        for every embedded "image"-type part referenced by `tex_source`
        (via \\includegraphics{filename}) -- pass it straight through to
        compile_latex_to_pdf() so those files exist in the compile
        directory. Empty if no question has an image component.

    Raises:
        ValueError: If `mode` is not one of "official", "example", or
            "solutions".
    """
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}, got {mode!r}")

    modules = sorted({
        q.get("Module") for q, _, _ in questions_with_marks
        if q.get("Module") and str(q.get("Module")).strip()
    })
    subtitle_bits = []
    if description and description.strip():
        subtitle_bits.append(escape_latex(description.strip()))
    if modules:
        subtitle_bits.append(escape_latex("Module(s): " + ", ".join(modules)))
    if mode == "solutions":
        subtitle_bits.append(r"\textbf{Solutions}")
    elif mode == "example":
        subtitle_bits.append(r"\textit{Example paper for revision}")
    subtitle = r"\\[0.15cm]".join(subtitle_bits)

    doc = [_HEADER % {
        "name": escape_latex(name),
        "subtitle": subtitle,
        "total": total_marks,
    }]

    assets, image_filenames = _collect_image_assets(questions_with_marks)

    for i, (question, marks, parts) in enumerate(questions_with_marks, start=1):
        doc.append(_render_question(i, question, marks, parts, mode, image_filenames))

    if mode == "official":
        # Blank continuation pages at the end of the printed booklet, for
        # anyone who ticked "continue at the end of the booklet" on a
        # question. Not needed for "example"/"solutions" -- those aren't
        # printed and written in.
        doc.append(_render_continuation_pages(3))

    doc.append(_FOOTER)
    return "\n".join(doc), assets


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def find_latex_engine() -> str:
    """Find an available LaTeX engine on this machine.

    Checks for pdflatex, xelatex, and tectonic, in that order.

    Returns:
        The full path to the first available engine found.

    Raises:
        LatexCompileError: If none of the supported engines are
            installed.
    """
    for engine in ("pdflatex", "xelatex", "tectonic"):
        path = shutil.which(engine)
        if path:
            return path
    raise LatexCompileError(
        "No LaTeX engine (pdflatex / xelatex / tectonic) was found on this "
        "computer. Install a LaTeX distribution (e.g. TeX Live or MiKTeX), "
        "or download the .tex source below and compile it elsewhere "
        "(e.g. Overleaf)."
    )


def compile_latex_to_pdf(tex_source: str, timeout: int = 60, assets: dict = None) -> bytes:
    """Compile LaTeX source to a PDF.

    Args:
        tex_source: The full .tex document source, as produced by
            build_latex().
        timeout: Seconds to allow each LaTeX engine invocation to run
            before giving up.
        assets: Optional {filename: raw_bytes} map (as returned by
            build_latex()) -- e.g. embedded images referenced via
            \\includegraphics{filename} in `tex_source`. Each is written
            into the same directory as the .tex file before compiling,
            so the LaTeX engine can find them by that relative filename.

    Returns:
        The compiled PDF file's raw bytes.

    Raises:
        LatexCompileError: If no LaTeX engine is available, compilation
            fails, or compilation times out.
    """
    engine = find_latex_engine()

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = os.path.join(tmpdir, "exam.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_source)

        for filename, data in (assets or {}).items():
            with open(os.path.join(tmpdir, filename), "wb") as asset_file:
                asset_file.write(data)

        is_tectonic = os.path.basename(engine).startswith("tectonic")
        result = None
        # Run twice for engines like pdflatex/xelatex so numbering/refs
        # settle; tectonic handles this internally in one pass.
        passes = 1 if is_tectonic else 2
        for _ in range(passes):
            if is_tectonic:
                cmd = [engine, "--outdir", tmpdir, tex_path]
            else:
                cmd = [
                    engine,
                    "-interaction=nonstopmode",
                    "-halt-on-error",
                    f"-output-directory={tmpdir}",
                    tex_path,
                ]
            try:
                result = subprocess.run(
                    cmd,
                    cwd=tmpdir,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise LatexCompileError("LaTeX compilation timed out.") from exc

        pdf_path = os.path.join(tmpdir, "exam.pdf")
        if not os.path.exists(pdf_path):
            log_tail = ((result.stdout or "") + "\n" + (result.stderr or ""))[-2000:]
            raise LatexCompileError(f"LaTeX compilation failed:\n{log_tail}")

        with open(pdf_path, "rb") as f:
            return f.read()
