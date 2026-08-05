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
}


def escape_latex(text) -> str:
    """Escape a plain string so it's safe to drop into LaTeX source."""
    if text is None:
        return ""
    text = str(text)
    return "".join(_LATEX_SPECIAL_CHARS.get(ch, ch) for ch in text)


def _paragraphs(text: str) -> str:
    """Turn blank-line-separated plain text into LaTeX paragraphs, escaping
    each line first. Single newlines become LaTeX line breaks."""
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
    """A shaded "Solution:" box shown inline in place of blank answer
    space, used by the "solutions" export mode."""
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


def _render_question(number: int, question: dict, marks: int, parts: list, mode: str = "official") -> str:
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
        lines.append(r"\begin{itemize}")

        # Tracks how many sub-questions have been placed on the current
        # page since the last forced page break, so we can enforce the
        # "max 2 sub-questions per page" rule below. Only relevant when
        # blank answer space is actually being reserved (official/example);
        # "solutions" mode doesn't reserve space so pages fill naturally.
        items_since_break = 0

        for idx, part in enumerate(parts):
            is_last = (idx == len(parts) - 1)

            label = escape_latex(part.get("Label") or "")
            desc = escape_latex(part.get("Description") or "")
            part_marks = part.get("Marks")
            marks_suffix = r" \hfill \textbf{[%d]}" % part_marks if part_marks else ""
            lines.append(r"\item[(%s)] %s%s" % (label, desc, marks_suffix))

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

        lines.append(r"\end{itemize}")
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
    """`count` genuinely blank pages appended to the very end of the
    "official" (printed) booklet, for anyone who ticked "continue at the
    end of the booklet" on a question and needs more room than what was
    reserved inline. No label text -- just blank writing space."""
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
) -> str:
    """Build a full .tex document.

    `questions_with_marks` is a list of (question_dict, marks, parts_list)
    tuples, already in the order they should appear on the paper.

    `mode` is one of "official" (the printed exam paper -- blank answer
    space, tick lines, blank continuation pages at the end), "example" (a
    revision/practice paper -- blank answer space but no tick lines or
    continuation pages, since it isn't printed and handed in), or
    "solutions" (the same questions as "example" but with each answer
    shown inline in a shaded box instead of blank space, for students to
    self-mark against after attempting "example").
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

    for i, (question, marks, parts) in enumerate(questions_with_marks, start=1):
        doc.append(_render_question(i, question, marks, parts, mode))

    if mode == "official":
        # Blank continuation pages at the end of the printed booklet, for
        # anyone who ticked "continue at the end of the booklet" on a
        # question. Not needed for "example"/"solutions" -- those aren't
        # printed and written in.
        doc.append(_render_continuation_pages(3))

    doc.append(_FOOTER)
    return "\n".join(doc)


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def find_latex_engine() -> str:
    """Return the path to the first available LaTeX engine, or raise."""
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


def compile_latex_to_pdf(tex_source: str, timeout: int = 60) -> bytes:
    """Compile `tex_source` to a PDF and return the PDF file's bytes.

    Raises LatexCompileError if no engine is available or compilation fails.
    """
    engine = find_latex_engine()

    with tempfile.TemporaryDirectory() as tmpdir:
        tex_path = os.path.join(tmpdir, "exam.tex")
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_source)

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
