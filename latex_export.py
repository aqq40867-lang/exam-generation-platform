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


def escape_latex(text) -> str:
    """Escape a plain string so it's safe to drop into LaTeX source.

    Args:
        text: Value to escape. Converted with `str()`; `None` becomes an
            empty string.

    Returns:
        The input with LaTeX special characters (backslash, &, %, $, #,
        _, {, }, ~, ^, <, >) replaced by their escaped equivalents.
    """
    if text is None:
        return ""
    text = str(text)
    return "".join(_LATEX_SPECIAL_CHARS.get(ch, ch) for ch in text)


def _paragraphs(text: str) -> str:
    """Convert blank-line-separated plain text into LaTeX paragraphs.

    Each block of text is escaped first; single newlines within a block
    become LaTeX line breaks rather than starting a new paragraph.

    Args:
        text: Plain text, with paragraphs separated by a blank line.

    Returns:
        The escaped text, reassembled as LaTeX paragraphs.
    """
    escaped = escape_latex(text)
    blocks = [block.strip() for block in escaped.split("\n\n") if block.strip()]
    if not blocks:
        return ""
    return "\n\n".join(block.replace("\n", r" \\ ") for block in blocks)


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

_HEADER = r"""\documentclass[12pt]{article}
\usepackage[a4paper, margin=2.5cm]{geometry}
\usepackage[utf8]{inputenc}
\usepackage{amssymb}
\usepackage{xcolor}
\usepackage{framed}
\usepackage{longtable}
\usepackage{graphicx}
\definecolor{shadecolor}{gray}{0.92}
\setlength{\parindent}{0pt}
\setlength{\parskip}{6pt}

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


def _render_table_part(part: dict, mode: str) -> str:
    """Render a bordered LaTeX table for a "table"-type part.

    Used for step-by-step / tracing questions -- see database.py's
    replace_question_parts docstring for the "Table spec" shape this
    reads.

    "given_columns" are filled in on every export mode (they're
    information the student is handed, e.g. the edges of a graph and their
    weights). "answer_columns" are left blank on official/example papers
    so the student has somewhere to write, and filled in on the solutions
    export. Row height is stretched on official/example so there's
    actually room to write in the blank cells; solutions uses a normal,
    compact row height since nothing needs to be written by hand there.

    Args:
        part: The question part dict, expected to hold a "Table spec".
        mode: Export mode ("official", "example", or "solutions");
            controls whether answer columns are filled in.

    Returns:
        LaTeX source for the table, or an escaped placeholder message if
        the part has no columns or rows configured yet.
    """
    spec = part.get("Table spec") or {}
    given_cols = [str(c) for c in (spec.get("given_columns") or [])]
    answer_cols = [str(c) for c in (spec.get("answer_columns") or [])]
    rows = spec.get("rows") or []
    headers = given_cols + answer_cols
    n = len(headers)

    if n == 0 or not rows:
        return escape_latex("(This table has not been configured yet.)")

    col_spec = "|" + "|".join(["l"] * n) + "|"
    header_row = " & ".join(r"\textbf{%s}" % escape_latex(h) for h in headers) + r" \\ \hline"

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
    lines.append(r"\renewcommand{\arraystretch}{%s}" % ("1.3" if mode == "solutions" else "2.4"))
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
        rendered = []
        for i in range(n):
            cell = cells[i] if i < len(cells) else ""
            if i < len(given_cols) or mode == "solutions":
                rendered.append(escape_latex(cell))
            else:
                rendered.append("")  # blank answer cell for official/example
        lines.append(" & ".join(rendered) + r" \\ \hline")
    lines.append(r"\end{longtable}")
    lines.append(r"\endgroup")
    lines.append(r"\renewcommand{\arraystretch}{1}")
    return "\n".join(lines)


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
    """Decode every "image"-type part's base64 image data exactly once.

    Each decoded image is assigned a short filesystem-safe filename.

    Args:
        questions_with_marks: List of (question_dict, marks, parts_list)
            tuples, as passed to build_latex().

    Returns:
        A tuple (assets, filenames): `assets` is {filename: raw_bytes},
        handed to compile_latex_to_pdf() to write into the compile
        directory before running the LaTeX engine. `filenames` maps
        id(part) -> filename, so _render_image_part() can look up the
        right file while walking the same part dicts -- keyed by Python
        object identity rather than a database id, since a not-yet-saved
        preview's parts don't have a database id yet at all.
    """
    assets = {}
    filenames = {}
    counter = 0
    for _question, _marks, parts in questions_with_marks:
        for part in parts:
            if (part.get("Part type") or "text") != "image":
                continue
            raw_b64 = part.get("Image data")
            if not raw_b64:
                continue
            try:
                data = base64.b64decode(raw_b64)
            except (ValueError, TypeError):
                continue
            counter += 1
            filename = f"img_{counter}.{_sniff_image_extension(data)}"
            assets[filename] = data
            filenames[id(part)] = filename
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


def _render_image_part(part: dict, image_filenames: dict) -> str:
    """Render a non-gradable embedded image, centered on the page.

    The part's "Description", if any, is shown underneath as an optional
    caption.

    Args:
        part: The question part dict for this "image"-type part.
        image_filenames: The id(part) -> filename map built by
            _collect_image_assets(). The actual file must already have
            been written into the compile directory by the time this is
            used.

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
    caption = part.get("Description")
    if caption and str(caption).strip():
        lines.append(r"\\[4pt]")
        lines.append(r"{\small\itshape %s}" % escape_latex(caption))
    lines.append(r"\end{center}")
    return "\n".join(lines)


def _render_question(
    number: int, question: dict, marks: int, parts: list, mode: str = "official",
    image_filenames: dict = None,
) -> str:
    """Render one full exam question, including all of its parts.

    Renders the question's own text/context, then walks its parts in
    order: material/image stimulus content is rendered inline, and
    lettered sub-questions are rendered inside an itemize list, each with
    reserved blank answer space (or a shaded solution box, in
    "solutions" mode). If the question has no parts, the same blank
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
        r"\noindent\textbf{Question %d} \hfill \textbf{[%d marks]}\\"
        % (number, marks)
    )
    lines.append(_paragraphs(question.get("Question", "")))

    main_context = question.get("Main question")
    if main_context and str(main_context).strip():
        lines.append("")
        lines.append(_paragraphs(main_context))

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
            desc = escape_latex(part.get("Description") or "")
            part_marks = part.get("Marks")
            marks_suffix = r" \hfill \textbf{[%d]}" % part_marks if part_marks else ""
            lines.append(r"\item[(%s)] %s%s" % (label, desc, marks_suffix))

            if part_type == "table":
                # A table's own rows are its "answer space" -- no blank
                # \vspace, no "tick here if you continue" line, and no
                # separate Solution box in "solutions" mode (the table
                # itself just gets filled in instead).
                lines.append(_render_table_part(part, mode))
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
