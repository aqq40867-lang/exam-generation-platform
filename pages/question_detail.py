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


def _render_part_table(part: dict):
    """Render a "table"-type sub-question's rows/columns as a grid.

    Lets the table's content be seen directly on this page without
    having to open Edit to find out what it holds. See database.py's
    replace_question_parts docstring for the "Table spec" shape this
    reads.

    Args:
        part: The question part dict, expected to hold a "Table spec".
    """
    spec = part.get("Table spec") or {}
    given_cols = spec.get("given_columns") or []
    answer_cols = spec.get("answer_columns") or []
    rows = spec.get("rows") or []
    headers = given_cols + answer_cols

    if not headers or not rows:
        ui.label("(Table not configured yet.)").classes("text-sm text-grey-500 italic mt-1")
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
    ui.label(
        "Columns marked “(answer)” are left blank on the official/example "
        "paper and filled in on the solutions export."
    ).classes("text-xs text-grey-500 mt-1")


def _render_part_image(part: dict):
    """Render an "image"-type component's embedded picture and caption.

    Lets the image be seen directly on this page without opening Edit
    (which, for a question containing one of these, is blocked anyway --
    see edit_question.py).

    Args:
        part: The question part dict, expected to hold "Image data" and
            an optional "Description" caption.
    """
    image_data = part.get("Image data")
    if not image_data:
        ui.label("(No image uploaded yet.)").classes("text-sm text-grey-500 italic mt-1")
        return
    mime = mimetypes.guess_type(part.get("Image filename") or "")[0] or "image/png"
    ui.image(f"data:{mime};base64,{image_data}").classes("max-w-md border rounded mt-1")
    caption = part.get("Description")
    if caption and str(caption).strip():
        ui.label(caption).classes("text-xs text-grey-600 italic mt-1")


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

            main_text = question.get("Main question")
            if main_text and str(main_text).strip():
                ui.label(main_text).classes("whitespace-pre-line mb-3")

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
                                with ui.row().classes("w-full items-start justify-between no-wrap"):
                                    ui.label(
                                        f"({part.get('Label')}) {part.get('Description') or ''}"
                                    ).classes("font-semibold flex-grow")
                                    ui.label(f"[{part.get('Marks', 0)}]").classes("text-grey-600")

                            if part_type == "table":
                                _render_part_table(part)
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
                                        part.get("Answer") or "(no standard answer recorded)"
                                    ).classes("whitespace-pre-line")
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
                """Compile this question to a PDF and offer it for download.

                Builds a single-question "example"-mode export via
                build_latex()/compile_latex_to_pdf(), then triggers a
                browser download of the result, or shows a notification
                if compilation fails.
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

                ui.download(pdf_bytes, filename="question_preview.pdf")
                ui.notify("Preview generated -- check your downloads.", color="positive")

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
