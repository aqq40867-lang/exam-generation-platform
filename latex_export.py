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


def _render_question(number: int, question: dict, marks: int, parts: list) -> str:
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
        for part in parts:
            label = escape_latex(part.get("Label") or "")
            desc = escape_latex(part.get("Description") or "")
            lines.append(r"\item[(%s)] %s" % (label, desc))
        lines.append(r"\end{itemize}")

    lines.append("")
    lines.append(r"\vspace{0.8cm}")
    return "\n".join(lines)


def _render_answer_key(questions_with_marks: list) -> str:
    lines = [r"\newpage", r"\begin{center}{\LARGE \textbf{Answer Key}}\end{center}", r"\vspace{0.4cm}"]
    for i, (question, marks, parts) in enumerate(questions_with_marks, start=1):
        lines.append(r"\noindent\textbf{Question %d}\\" % i)
        answer = question.get("Answer")
        if answer and str(answer).strip():
            lines.append(_paragraphs(answer))
        if parts:
            for part in parts:
                if part.get("Answer") and str(part.get("Answer")).strip():
                    label = escape_latex(part.get("Label") or "")
                    lines.append(r"\textit{(%s)} %s\\" % (label, _paragraphs(part.get("Answer"))))
        lines.append(r"\vspace{0.5cm}")
    return "\n".join(lines)


def build_latex(
    name: str,
    description: str,
    total_marks: int,
    questions_with_marks: list,
    include_answers: bool = False,
) -> str:
    """Build a full .tex document.

    `questions_with_marks` is a list of (question_dict, marks, parts_list)
    tuples, already in the order they should appear on the paper.
    """
    modules = sorted({
        q.get("Module") for q, _, _ in questions_with_marks
        if q.get("Module") and str(q.get("Module")).strip()
    })
    subtitle_bits = []
    if description and description.strip():
        subtitle_bits.append(escape_latex(description.strip()))
    if modules:
        subtitle_bits.append(escape_latex("Module(s): " + ", ".join(modules)))
    subtitle = r"\\[0.15cm]".join(subtitle_bits)

    doc = [_HEADER % {
        "name": escape_latex(name),
        "subtitle": subtitle,
        "total": total_marks,
    }]

    for i, (question, marks, parts) in enumerate(questions_with_marks, start=1):
        doc.append(_render_question(i, question, marks, parts))

    if include_answers:
        doc.append(_render_answer_key(questions_with_marks))

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
