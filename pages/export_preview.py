"""NiceGUI page that renders a live, compiled preview of an in-progress exam.

Reads the draft snapshot the Export Exam Paper page writes to
``app.storage.user["exam_draft"]`` when its "Preview" button is clicked,
compiles it to a real PDF via the same LaTeX pipeline used for the final
export (so the preview matches the actual printed layout exactly), and
embeds it inline. Unlike Generate, Preview doesn't require the exam's
marks to add up to its full marks total -- it's meant to be usable at any
point while still assembling the exam.
"""

import uuid
from collections import OrderedDict

from fastapi import Response
from nicegui import ui, app, run

from database import get_question, get_question_parts
from latex_export import build_latex, compile_latex_to_pdf, LatexCompileError

# In-memory hand-off from a compiled preview to the /exams/preview.pdf
# route below: embedding the PDF as a base64 data: URI iframe looked
# right on the Python side (the element gets created) but rendered blank
# in the browser -- Chromium's built-in PDF viewer doesn't reliably open
# data: URIs inside an <iframe>. Serving the bytes from a real URL is the
# fix. Capped and FIFO-evicted so it can't grow unbounded across many
# previews; entries are short-lived (a teacher previews, looks, moves on).
_MAX_CACHED_PREVIEWS = 20
_preview_pdfs: "OrderedDict[str, bytes]" = OrderedDict()


def _cache_preview_pdf(pdf_bytes: bytes) -> str:
    """Stash compiled PDF bytes under a fresh token and return that token."""
    token = uuid.uuid4().hex
    _preview_pdfs[token] = pdf_bytes
    while len(_preview_pdfs) > _MAX_CACHED_PREVIEWS:
        _preview_pdfs.popitem(last=False)
    return token


@app.get("/exams/preview.pdf")
def _serve_preview_pdf(token: str = ""):
    """Serve a previously compiled preview PDF by its one-time token.

    Registered once at import time (not inside export_preview_page) --
    this is a plain FastAPI route, not a NiceGUI page.
    """
    data = _preview_pdfs.get(token)
    if data is None:
        return Response(status_code=404, content=b"Preview expired or not found.")
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=preview.pdf"},
    )


def export_preview_page():
    """Render the exam preview page.

    Rebuilds the exam described by the draft in
    ``app.storage.user["exam_draft"]`` (written by the Export page's
    Preview button), compiles it to PDF in the "official" (printable exam
    paper) layout, and shows it inline. Redirects to /login if not
    authenticated.
    """

    if not app.storage.user.get("logged_in"):
        ui.navigate.to("/login")
        return

    draft = app.storage.user.get("exam_draft")

    # No max-width cap and minimal padding -- unlike the other exam-builder
    # pages (which are forms, so a narrow max-w-5xl reading column makes
    # sense), this page is just a document viewer and should use as much
    # of the window as it can get.
    with ui.column().classes("w-full p-3 gap-2"):
        with ui.row().classes("w-full items-center gap-4"):
            ui.link("← Back to Export", "/exams/export").classes("text-sm")
            ui.label("Exam Preview").classes("text-xl font-bold")

        if not draft or not draft.get("items"):
            ui.label("There's nothing to preview yet.").classes(
                "text-grey-600 font-semibold mt-2"
            )
            ui.label(
                "Go back to the Export page, set up your exam, and click "
                "Preview."
            ).classes("text-sm text-grey-600")
            ui.button(
                "Go to Export Page", on_click=lambda: ui.navigate.to("/exams/export")
            )
            return

        # Compiling takes a few seconds, so the page renders immediately
        # with a spinner, then swaps in the result (or an error) once the
        # background compile finishes -- see compile_and_render() below.
        status_area = ui.column().classes("w-full items-center gap-2 py-8")
        preview_area = ui.column().classes("w-full")

        with status_area:
            ui.spinner(size="lg")
            ui.label("Compiling preview…").classes("text-grey-600")

        async def compile_and_render():
            """Compile the draft exam to PDF and embed it, or show the error.

            Runs once, shortly after the page first renders (kicked off
            by the one-shot timer below) so the spinner has a chance to
            show up before the (blocking) LaTeX compile starts.
            """
            # Everything -- including the "success" steps at the end -- is
            # inside one try/except: this whole function runs detached
            # from the request that triggered it (fired by the timer
            # below), so an exception anywhere in here would otherwise be
            # logged server-side only and leave the page stuck wherever
            # it last got to (e.g. spinner already cleared, nothing put
            # in its place) with no visible clue why.
            try:
                questions_with_marks = []
                missing = []
                for item in draft["items"]:
                    question = get_question(item["question_id"])
                    if not question:
                        missing.append(item["question_id"])
                        continue
                    parts = get_question_parts(question["id"])
                    questions_with_marks.append(
                        (question, int(item.get("marks") or 0), parts)
                    )

                if not questions_with_marks:
                    status_area.clear()
                    with status_area:
                        ui.label(
                            "None of the previewed questions could be found "
                            "(they may have been deleted since). Go back to "
                            "Export and refresh your selection."
                        ).classes("text-red-600")
                    return

                tex_source, assets = build_latex(
                    draft.get("name") or "New Exam",
                    draft.get("description") or "",
                    int(draft.get("total_marks") or 0),
                    questions_with_marks,
                    mode="official",
                )
                pdf_bytes = await run.io_bound(compile_latex_to_pdf, tex_source, 60, assets)

                status_area.clear()
                if missing:
                    with status_area:
                        ui.label(
                            f"Note: {len(missing)} previewed question(s) could "
                            "no longer be found and were skipped."
                        ).classes("text-sm text-orange-700")

                token = _cache_preview_pdf(pdf_bytes)
                with preview_area:
                    # sanitize=False: ui.html() otherwise runs its content
                    # through DOMPurify client-side, which strips <iframe>
                    # tags outright (a security default -- DOMPurify
                    # doesn't allow iframes unless told to) regardless of
                    # what they point at. Safe here since the URL is
                    # entirely our own (a freshly minted token), not
                    # user-supplied content.
                    # NiceGUI's flex containers default to
                    # align-items: flex-start, so a child shrink-wraps to
                    # its own content width instead of stretching -- the
                    # iframe's width:100% below has nothing concrete to
                    # size against unless this wrapper itself is forced
                    # to fill the row (w-full + an explicit inline width).
                    ui.html(
                        f'<iframe src="/exams/preview.pdf?token={token}" '
                        'style="width:100%; height:calc(100vh - 120px); '
                        'min-height:900px; border:1px solid #ddd; '
                        'display:block;"></iframe>',
                        sanitize=False,
                    ).classes("w-full").style("width:100%; display:block;")
            except LatexCompileError as exc:
                status_area.clear()
                with status_area:
                    ui.label("Couldn't compile the preview:").classes(
                        "text-red-600 font-semibold"
                    )
                    ui.label(str(exc)).classes(
                        "text-sm text-red-600 whitespace-pre-line"
                    )
            except Exception as exc:
                # Safety net: surfaces any other bug here (a bad draft
                # shape, a DB hiccup, etc.) on screen instead of leaving
                # the page stuck with no clue why.
                status_area.clear()
                with status_area:
                    ui.label("Something went wrong building the preview:").classes(
                        "text-red-600 font-semibold"
                    )
                    ui.label(f"{type(exc).__name__}: {exc}").classes(
                        "text-sm text-red-600 whitespace-pre-line"
                    )

        ui.timer(0.1, compile_and_render, once=True)
