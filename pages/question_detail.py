"""NiceGUI page for viewing a single question's full detail.

Shows the question's content (main text, sub-questions and their
answers, and any table/image/material components) up front, with a PDF
preview action and a collapsed "bookkeeping" section for secondary
metadata (status, version, usage, timestamps).
"""

import mimetypes

from nicegui import ui, app, run
from database import get_question, delete_question, load_questions, get_question_parts
from latex_export import build_latex, compile_latex_to_pdf, LatexCompileError
from pages.create_question import _cache_preview_pdf


def _render_one_table(spec: dict, *, empty_message: str):
    """Render one {"given_columns", "answer_columns", "rows"} spec as a grid.

    Shared by the problem-table and answer-table displays below --
    columns are shown in given-then-answer order with no masking (the
    problem table and the answer table are two independent tables now,
    see database.py's replace_question_parts docstring, so whatever a
    cell holds -- including blank -- is shown exactly as stored).

    Args:
        spec: A {"given_columns", "answer_columns", "rows"} dict, or None.
        empty_message: Placeholder text shown if `spec` has no columns or
            rows configured yet.
    """
    spec = spec or {}
    given_cols = spec.get("given_columns") or []
    answer_cols = spec.get("answer_columns") or []
    rows = spec.get("rows") or []
    headers = given_cols + answer_cols

    if not headers or not rows:
        ui.label(empty_message).classes("text-sm text-grey-500 italic mt-1")
        return

    columns = []
    for i, h in enumerate(headers):
        is_answer = i >= len(given_cols)
        columns.append({
            "name": f"col{i}",
            "label": f"{h} (answer)" if is_answer else str(h),
            "field": f"col{i}",
            "align": "left",
        })

    table_rows = []
    for r_idx, row in enumerate(rows):
        cells = list(row) + [""] * max(0, len(headers) - len(row))
        row_dict = {f"col{i}": cells[i] if i < len(cells) else "" for i in range(len(headers))}
        row_dict["_id"] = r_idx
        table_rows.append(row_dict)

    ui.table(columns=columns, rows=table_rows, row_key="_id").classes("w-full mt-1").props("dense flat bordered")


def _render_part_image(part: dict, *, caption=None):
    """Render an embedded image and, optionally, a caption underneath.

    Lets the image be seen directly on this page without opening Edit
    (which, for a question with an attached image, is blocked anyway --
    see edit_question.py).

    Args:
        part: The question part dict, expected to hold "Image data".
        caption: Caption text shown underneath. If omitted (None), falls
            back to the part's own "Description" -- correct for a legacy
            standalone "image"-type part, where "Description" is only
            ever used as this caption. Pass "" explicitly to suppress it
            (used when the image is attached to a "text"/"table"
            sub-question whose "Description" is its own text, already
            shown above).
    """
    image_data = part.get("Image data")
    if not image_data:
        ui.label("(No image uploaded yet.)").classes("text-sm text-grey-500 italic mt-1")
        return
    mime = mimetypes.guess_type(part.get("Image filename") or "")[0] or "image/png"
    ui.image(f"data:{mime};base64,{image_data}").classes("max-w-md border rounded mt-1")
    if caption is None:
        caption = part.get("Description")
    if caption and str(caption).strip():
        ui.label(caption).classes("text-xs text-grey-600 italic mt-1")


def _render_blocks(blocks: list) -> None:
    """Render an ordered list of text/image/table content blocks.

    Shared by _render_part_blocks() (a sub-problem's own blocks, minus
    whichever leading one is shown inline in its header) and
    question_detail_page() directly (the question's own "Main content
    blocks" -- its overall problem statement, which has no header line
    to inline a first block into).

    Args:
        blocks: An ordered list of content block dicts (see database.py's
            get_question_parts() / get_question() for the shape).
    """
    for block in blocks:
        btype = block.get("type")
        if btype == "text":
            text = (block.get("text") or "").strip()
            if text:
                ui.label(text).classes("whitespace-pre-line mt-1")
        elif btype == "image":
            image_data = block.get("image_data")
            if not image_data:
                ui.label("(No image uploaded yet.)").classes("text-sm text-grey-500 italic mt-1")
                continue
            mime = mimetypes.guess_type(block.get("image_filename") or "")[0] or "image/png"
            ui.image(f"data:{mime};base64,{image_data}").classes("max-w-md border rounded mt-1")
        elif btype == "table":
            ui.label("Problem table (shown to the student):").classes(
                "text-xs font-bold text-grey-600 mt-1"
            )
            _render_one_table(block.get("table_spec"), empty_message="(Table not configured yet.)")
            # The standard answer for a table sub-question is free text,
            # shown in this part's own "Answer:" card below (see
            # question_detail_page()) -- same as a text-only sub-question's
            # -- not as a second mirrored table here.


def _render_part_blocks(part: dict) -> None:
    """Render a gradable ("text"/"table") part's ordered content blocks.

    Mirrors latex_export.py's block rendering (see its _render_question):
    the first block, if it's text, is shown inline in the header line by
    the caller (question_detail_page, right next to the label/marks), so
    only every *other* block -- a non-first text block, an image, or a
    table -- is rendered here, each as its own line, in order. This is
    what makes this page's preview match the exported PDF's layout
    instead of the old fixed "description, then image, then table" one.

    Args:
        part: The question part dict, expected to hold "Content blocks"
            (see database.py's get_question_parts).
    """
    blocks = part.get("Content blocks") or []
    first_is_text = bool(blocks) and blocks[0].get("type") == "text"
    remaining = blocks[1:] if first_is_text else blocks
    _render_blocks(remaining)


def question_detail_page(question_id: int):
    """Render the question detail page.

    Laid out as "content first, bookkeeping second": what the question
    actually asks and what its answer(s) are is the whole reason to open
    this page, so it's the large, top-of-page block -- including sub-
    question answers and table contents, which the previous version of
    this page didn't render at all. Status/version/usage/timestamps are
    real but secondary, so they're collapsed into a details section
    instead of interleaved at equal visual weight with the actual content.

    Args:
        question_id: The database id of the question to display, taken
            from the page route. Redirects to the question list if the
            user isn't logged in, the question doesn't exist, or the
            current user isn't its creator.
    """

    # Check login
    if not app.storage.user.get("logged_in"):
        ui.navigate.to("/login")
        return

    # Get question data
    question = get_question(question_id)

    if not question:
        ui.notify("Question not found.", color="negative")
        ui.navigate.to("/questions")
        return

    username = app.storage.user["username"]

    # Only the creator can view this question
    if question.get("Created by") != username:
        ui.notify("You do not have permission to view this question.", color="negative")
        ui.navigate.to("/questions")
        return

    # Work out this question's per-user display number (1, 2, 3... per creator),
    # independent of the real database id used in the URL
    user_questions = sorted(
        (q for q in load_questions() if q.get("Created by") == username),
        key=lambda q: q["id"]
    )
    user_question_ids = [q["id"] for q in user_questions]
    display_id = user_question_ids.index(question_id) + 1 if question_id in user_question_ids else question_id

    parts = get_question_parts(question_id)

    with ui.column().classes("w-full max-w-4xl mx-auto p-8 gap-4"):

        ui.label(f"Question Detail #{display_id}").classes("text-3xl font-bold")

        # ------------------------------------------------------------
        # Content: title, module, shared material, and every sub-question
        # with its answer (or, for a "table" part, its actual table)
        # shown inline.
        # ------------------------------------------------------------
        with ui.card().classes("w-full p-6"):

            with ui.row().classes("w-full items-start justify-between no-wrap"):
                ui.label(question.get("Question") or "N/A").classes("text-2xl font-bold")
                with ui.row().classes("gap-1 items-center"):
                    if question.get("Topic"):
                        ui.badge(question["Topic"]).props("color=blue-6")
                    if question.get("Module"):
                        ui.badge(question["Module"]).classes("text-sm")

            ui.label(f"{question.get('Marks', 'N/A')} marks total").classes("text-sm text-grey-600 mb-2")

            # "Main content blocks" -- the question's overall problem
            # statement, built from the same text/image/table block
            # editor a sub-problem's own content uses -- is what
            # get_question() returns here; it already falls back to a
            # single synthesized text block from the legacy flat "Main
            # question" field for rows saved before this feature existed
            # (see database.py's _decode_main_blocks), so this is always
            # the right thing to render regardless of how old the row is.
            main_blocks = question.get("Main content blocks") or []
            if main_blocks:
                with ui.column().classes("w-full gap-0 mb-3"):
                    _render_blocks(main_blocks)

            if parts:
                with ui.column().classes("w-full gap-3"):
                    for part in parts:
                        part_type = part.get("Part type") or "text"
                        is_gradable = part_type in ("text", "table")

                        with ui.column().classes("w-full border-t pt-3 gap-0"):
                            if is_gradable:
                                # Only "text"/"table" components are
                                # lettered sub-questions with marks --
                                # "material"/"image" are stimulus content,
                                # so they skip this header entirely and
                                # just show their content directly below.
                                # The header line itself shows the part's
                                # *first* content block if it's text --
                                # exactly like the exported PDF's
                                # "\item[(a)] ..." line -- with every
                                # other block (more text, an image, a
                                # table) rendered below by
                                # _render_part_blocks(), in order.
                                blocks = part.get("Content blocks") or []
                                first_text = (
                                    blocks[0].get("text")
                                    if blocks and blocks[0].get("type") == "text"
                                    else ""
                                )
                                with ui.row().classes("w-full items-start justify-between no-wrap"):
                                    ui.label(
                                        f"({part.get('Label')}) {first_text or ''}"
                                    ).classes("font-semibold flex-grow")
                                    ui.label(f"[{part.get('Marks', 0)}]").classes("text-grey-600")

                                _render_part_blocks(part)

                                # A sub-problem broken down further into
                                # (i)/(ii)/(iii)... sub-parts (see
                                # database.py's get_question_parts) shows
                                # each of those instead of this
                                # sub-problem's own Answer card -- its own
                                # marks/answer are unused once it has
                                # sub-parts (create_question.py's
                                # _build_part_dict already reflects that:
                                # "Marks" is the sum of the sub-parts', and
                                # "Answer" is None).
                                sub_parts = part.get("Sub parts") or []
                                if sub_parts:
                                    with ui.column().classes(
                                        "w-full gap-2 mt-2 pl-4 border-l-2 border-grey-300"
                                    ):
                                        for sub_part in sub_parts:
                                            sub_blocks = sub_part.get("Content blocks") or []
                                            sub_first_text = (
                                                sub_blocks[0].get("text")
                                                if sub_blocks and sub_blocks[0].get("type") == "text"
                                                else ""
                                            )
                                            with ui.row().classes(
                                                "w-full items-start justify-between no-wrap"
                                            ):
                                                ui.label(
                                                    f"({part.get('Label')})({sub_part.get('Label')}) "
                                                    f"{sub_first_text or ''}"
                                                ).classes("font-semibold flex-grow")
                                                ui.label(f"[{sub_part.get('Marks', 0)}]").classes(
                                                    "text-grey-600"
                                                )

                                            _render_part_blocks(sub_part)

                                            with ui.card().classes("bg-grey-100 w-full p-3 mt-1"):
                                                ui.label("Answer:").classes(
                                                    "text-xs font-bold text-grey-600"
                                                )
                                                ui.label(
                                                    sub_part.get("Answer")
                                                    or "(no standard answer recorded)"
                                                ).classes("whitespace-pre-line")
                                else:
                                    with ui.card().classes("bg-grey-100 w-full p-3 mt-1"):
                                        ui.label("Answer:").classes("text-xs font-bold text-grey-600")
                                        ui.label(
                                            part.get("Answer") or "(no standard answer recorded)"
                                        ).classes("whitespace-pre-line")
                            elif part_type == "material":
                                ui.label(
                                    part.get("Description") or "(This material block is empty.)"
                                ).classes("whitespace-pre-line")
                            elif part_type == "image":
                                _render_part_image(part)
            else:
                with ui.card().classes("bg-grey-100 w-full p-3 mt-1"):
                    ui.label("Answer:").classes("text-xs font-bold text-grey-600")
                    ui.label(
                        question.get("Answer") or "(no standard answer recorded)"
                    ).classes("whitespace-pre-line")

            # ---------------------------------------------------------
            # Preview PDF: see this single question laid out exactly as
            # it would appear on an exported exam paper (pseudocode
            # formatting, table rendering, page breaks and all), instead
            # of trying to picture it from the plain description/answer
            # fields shown above.
            # ---------------------------------------------------------
            preview_ref = {}

            async def on_preview():
                """Compile this question to a PDF and open it inline in a new tab.

                Builds a single-question "example"-mode export via
                build_latex()/compile_latex_to_pdf(), then opens the result
                in a new browser tab (viewed inline via the browser's own
                PDF viewer, same as create_question.py's "Preview PDF")
                instead of forcing a download, or shows a notification if
                compilation fails.
                """
                marks = question.get("Marks") or 0
                # NOTE: kept in English -- this string is baked straight
                # into the LaTeX source and compiled with pdflatex, which
                # has no CJK glyphs at all (see the equivalent note in
                # create_question.py's on_preview for the full story).
                tex, assets = build_latex(
                    name=question.get("Question") or "Preview",
                    description="Preview",
                    total_marks=marks,
                    questions_with_marks=[(question, marks, parts)],
                    mode="example",
                )
                btn = preview_ref.get("btn")
                if btn is not None:
                    btn.props("loading")
                try:
                    try:
                        pdf_bytes = await run.io_bound(compile_latex_to_pdf, tex, 60, assets)
                    except LatexCompileError as exc:
                        ui.notify(str(exc), color="negative", multi_line=True, close_button=True)
                        return
                finally:
                    if btn is not None:
                        btn.props(remove="loading")

                token = _cache_preview_pdf(pdf_bytes)
                ui.navigate.to(f"/questions/preview.pdf?token={token}", new_tab=True)

            preview_ref["btn"] = ui.button(
                "Preview PDF", on_click=on_preview, color="secondary"
            ).props("outline").classes("mt-3")

        # ------------------------------------------------------------
        # Bookkeeping: real information, but not what you opened this
        # page to read -- collapsed by default, still reachable.
        # ------------------------------------------------------------
        with ui.expansion("Details (status, version, created by, usage...)").classes(
            "w-full border"
        ):
            with ui.grid(columns=2).classes("w-full gap-x-6 gap-y-1 p-2"):
                ui.label("Status:").classes("font-semibold text-grey-600")
                status = question.get("Status", "N/A")
                status_color = "green" if status == "Published" else "orange" if status == "Draft" else "grey"
                ui.label(status).classes(f"text-{status_color}-600")

                ui.label("Version:").classes("font-semibold text-grey-600")
                ui.label(str(question.get("Version", 1)))

                ui.label("Created by:").classes("font-semibold text-grey-600")
                ui.label(question.get("Created by", "N/A"))

                ui.label("Created at:").classes("font-semibold text-grey-600")
                ui.label(question.get("Created at", "N/A"))

                if "Updated at" in question:
                    ui.label("Updated at:").classes("font-semibold text-grey-600")
                    ui.label(question.get("Updated at") or "N/A")

                ui.label("Usage:").classes("font-semibold text-grey-600")
                ui.label(str(question.get("Usage", 0)))

        # Action buttons
        with ui.row().classes("gap-4 mt-2"):

            ui.button(
                "Back to List",
                on_click=lambda: ui.navigate.to("/questions")
            )

            ui.button(
                "Edit",
                on_click=lambda: ui.navigate.to(f"/questions/{question_id}/edit"),
                color="primary"
            )

            def confirm_delete():
                """Show a confirmation dialog before deleting this question."""
                with ui.dialog() as dialog, ui.card():
                    ui.label("Delete this question?").classes("text-lg")
                    ui.label("This action cannot be undone.").classes("text-sm text-grey-600")

                    with ui.row().classes("gap-4 mt-4"):
                        ui.button(
                            "Cancel",
                            on_click=dialog.close
                        )

                        def delete_question_confirmed():
                            """Delete the question, close the dialog, and return to the list."""
                            delete_question(question_id)
                            dialog.close()
                            ui.notify("Question deleted successfully.", color="positive")
                            ui.navigate.to("/questions")

                        ui.button(
                            "Delete",
                            color="red",
                            on_click=delete_question_confirmed
                        )

                dialog.open()

            ui.button(
                "Delete",
                color="red",
                on_click=confirm_delete
            )
