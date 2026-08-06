"""NiceGUI page for building and exporting an exam paper.

Question *selection* happens on the Question Bank page (/questions) --
a teacher ticks the questions they want there, and that selection (an
ordered list of question ids) is carried over via ``app.storage.user``.
This page is where they arrange the resulting exam: reorder or remove
picks, set each one's marks for this exam, optionally include an answer
key, preview the compiled layout, and finally generate a PDF (or raw
LaTeX source) once the marks add up to the exam's full marks total.
"""

import io
import zipfile
from datetime import datetime

from nicegui import ui, app, run

from database import (
    load_questions,
    get_question_parts,
    add_exam,
    add_question_to_exam,
)
from latex_export import build_latex, compile_latex_to_pdf, LatexCompileError


def export_exam_page():
    """Render the exam export page.

    Reads the question selection made on /questions out of
    ``app.storage.user["exam_selection"]`` (an ordered list of question
    ids), lets the teacher reorder/remove picks and set marks, then
    exports the result as a PDF (or LaTeX source) once the marks add up
    to the exam's full marks total. Redirects to /login if not
    authenticated.
    """

    # Check login
    if not app.storage.user.get("logged_in"):
        ui.navigate.to("/login")
        return

    username = app.storage.user["username"]

    # Only this teacher's own questions are eligible -- matches the
    # filtering /questions already applies before a question can be
    # ticked. Numbered the same way as /questions (1, 2, 3... per
    # teacher) so the id shown here matches what the teacher ticked.
    all_questions = load_questions()
    own_questions = [q for q in all_questions if q.get("Created by") == username]
    own_questions.sort(key=lambda q: q["id"])
    for display_id, q in enumerate(own_questions, start=1):
        q["display_id"] = display_id
    by_id = {q["id"]: q for q in own_questions}

    # Resolve the stored selection against this teacher's current
    # question set, in the order it was ticked (or last dragged into) --
    # silently dropping any id that's since been deleted. Writing the
    # cleaned-up list back to storage keeps /questions' checkboxes honest
    # if a stale id ever sneaks in.
    selected_order = app.storage.user.get("exam_selection", [])
    selected_questions = [by_id[qid] for qid in selected_order if qid in by_id]
    app.storage.user["exam_selection"] = [q["id"] for q in selected_questions]

    with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-4"):

        ui.link("← Back to Question Bank", "/questions").classes("text-sm")
        ui.label("Export Exam Paper").classes("text-2xl font-bold")
        ui.label(
            "Reorder or remove the questions you ticked in the Question "
            "Bank, set the marks each one is worth in this exam, then "
            "generate a PDF. If the marks don't add up to the full marks "
            "total yet, you'll get a heads-up but can still generate. To "
            "add more questions, go back to the Question Bank."
        ).classes("text-sm text-grey-600")

        if not selected_questions:
            ui.label(
                "No questions selected yet."
            ).classes("text-grey-600 font-semibold mt-2")
            ui.label(
                "Go to the Question Bank, tick the questions you want on "
                "this exam, then come back here."
            ).classes("text-sm text-grey-600")
            ui.button(
                "Go to Question Bank", on_click=lambda: ui.navigate.to("/questions")
            )
            return

        # -- Exam settings -----------------------------------------------
        with ui.card().classes("w-full p-4"):
            with ui.row().classes("w-full items-end gap-4"):
                exam_name = ui.input("Exam Name", value="New Exam").classes("w-64")
                total_marks_input = ui.number(
                    "Full Marks (target total)", value=100, min=1
                ).classes("w-56")
            exam_description = ui.input("Description (optional)").classes("w-full")

            include_answers = ui.checkbox("Include answers")

        # -- Selection state -----------------------------------------------
        # One entry per selected question, in display/export order. Kept
        # as a plain Python list (rather than re-deriving order from the
        # DOM) so drag-reordering, removal, and marks edits all update a
        # single source of truth that gather_selected() reads from.
        items = [
            {"question": q, "marks": int(q.get("Marks") or 0)}
            for q in selected_questions
        ]

        status_label = ui.label().classes("text-lg font-bold")
        generate_btn = None  # assigned below, referenced by refresh_status()
        generate_tooltip = None  # assigned below, explains why the button is disabled
        download_tex_btn = None
        preview_btn = None

        def selected_total() -> int:
            """Return the sum of marks currently assigned across all items."""
            total = 0
            for entry in items:
                widget = entry.get("marks_input")
                total += int(widget.value or 0) if widget is not None else entry["marks"]
            return total

        def disabled_reason(count: int) -> str:
            """Explain why the Generate button is currently disabled.

            Shown as a tooltip on the button (a disabled button in Quasar
            has pointer-events disabled, so the tooltip is attached to a
            wrapper div around it instead -- see how generate_btn is
            created below). The marks total no longer has to match the
            full marks target to generate -- that mismatch is just
            surfaced as a warning at click time (see on_generate) -- so
            the only thing that still disables the button is having no
            questions at all.

            Args:
                count: Number of questions currently in the exam.

            Returns:
                A human-readable reason string, or '' if the button should
                not be disabled.
            """
            if count == 0:
                return "Add at least one question first (from the Question Bank)."
            return ""

        def refresh_status():
            """Refresh the status label and enable/disable the action buttons.

            Recomputes the item count and marks total against the target
            and updates the status label's text/color as a visual hint --
            but none of the buttons require the marks to add up anymore;
            they're all enabled as soon as there's at least one question.
            """
            total = selected_total()
            target = int(total_marks_input.value or 0)
            count = len(items)
            status_label.text = f"{count} question(s) — {total} / {target} marks"

            if count > 0 and total == target:
                status_label.classes(replace="text-lg font-bold text-green-700")
            else:
                status_label.classes(replace="text-lg font-bold text-red-600")

            if generate_btn is not None:
                generate_btn.enable() if count > 0 else generate_btn.disable()
            if generate_tooltip is not None:
                reason = disabled_reason(count)
                generate_tooltip.set_text(reason)
                generate_tooltip.set_visibility(bool(reason))
            if download_tex_btn is not None:
                download_tex_btn.enable() if count > 0 else download_tex_btn.disable()
            if preview_btn is not None:
                preview_btn.enable() if count > 0 else preview_btn.disable()

        total_marks_input.on_value_change(lambda e: refresh_status())

        # -- Reorderable question list -----------------------------------
        with ui.card().classes("w-full p-3"):
            with ui.row().classes(
                "w-full items-center font-bold px-2 pb-1 text-sm text-grey-600"
            ):
                ui.label("").classes("w-8")  # drag handle column
                ui.label("ID").classes("w-10")
                ui.label("Question").classes("flex-grow")
                ui.label("Default").classes("w-20 text-right")
                ui.label("Marks in exam").classes("w-32")
                ui.label("").classes("w-10")  # remove button column

            items_container = ui.column().classes("w-full gap-2")

            def remove_item(entry):
                """Drop one question from the exam and persist the change.

                Removes the row from the page, updates the in-memory
                ``items`` list, and writes the trimmed selection back to
                storage (so /questions' checkboxes reflect the removal
                too). If that empties the exam, reload the page so the
                "no questions selected" empty state takes over.
                """
                items.remove(entry)
                entry["row"].delete()
                app.storage.user["exam_selection"] = [e["question"]["id"] for e in items]
                if not items:
                    ui.navigate.to("/exams/export")
                    return
                refresh_status()

            def build_row(entry):
                """Render one draggable row for a selected question.

                Args:
                    entry: One of the dicts in ``items`` -- holds the
                        question dict and its current marks value; this
                        function attaches the row's marks-input widget
                        and root element back onto it.
                """
                q = entry["question"]
                default_marks = int(q.get("Marks") or 0)
                with ui.row().classes(
                    "w-full items-center gap-3 bg-grey-2 rounded-borders px-3 py-2"
                ) as row:
                    ui.icon("drag_indicator").classes(
                        "drag-handle cursor-move text-grey-600 w-8"
                    )
                    ui.label(f"#{q['display_id']}").classes("w-10 text-grey-700")
                    with ui.column().classes("flex-grow gap-0 min-w-0"):
                        ui.label(q.get("Question") or "").classes("truncate font-medium")
                        ui.label(q.get("Module") or "—").classes("text-xs text-grey-500")
                    ui.label(str(default_marks)).classes("w-20 text-right text-grey-500")

                    marks_input = ui.number(value=entry["marks"], min=0).classes("w-32")

                    def on_marks_change(e, entry=entry):
                        entry["marks"] = int(e.value or 0)
                        refresh_status()

                    marks_input.on_value_change(on_marks_change)
                    entry["marks_input"] = marks_input

                    ui.button(
                        icon="close",
                        on_click=lambda entry=entry: remove_item(entry),
                    ).props("flat round dense color=red").classes("w-10")
                entry["row"] = row

            with items_container:
                for entry in items:
                    build_row(entry)

            def on_reorder(e):
                """Keep ``items`` (and storage) in sync after a drag-reorder.

                The Sortable controller already moves the dragged row's
                element in the DOM/element tree by itself -- this just
                mirrors that same move in the plain-Python ``items`` list
                so gather_selected() and everything reading ``items``
                still matches what's on screen.
                """
                entry = items.pop(e.old_index)
                items.insert(e.new_index, entry)
                app.storage.user["exam_selection"] = [en["question"]["id"] for en in items]

            items_container.make_sortable(handle=".drag-handle", on_end=on_reorder)

        refresh_status()

        # -- Actions ---------------------------------------------------
        with ui.row().classes("w-full items-center gap-4 mt-2"):
            # The button itself is wrapped in a plain div. A disabled Quasar
            # button has pointer-events disabled, so it never sees mouse
            # hover and a tooltip attached directly to it would never show.
            # The wrapper div isn't disabled, so hovering anywhere over the
            # button's footprint still reaches it and triggers the tooltip.
            with ui.element("div") as generate_wrapper:
                generate_btn = ui.button("Generate & Download", color="primary")
            generate_tooltip = (
                ui.tooltip("")
                .props(f'target="#{generate_wrapper.html_id}"')
                .style("font-size: 14px")
            )
            download_tex_btn = ui.button("Download LaTeX Source (.tex)", color="secondary")
            preview_btn = ui.button("Preview", color="secondary").props("outline")
            generate_btn.disable()
            download_tex_btn.disable()
            preview_btn.disable()

        # Populate the tooltip's initial text/visibility now that
        # generate_tooltip exists (the first refresh_status() call above
        # ran before this button block, when it was still None).
        refresh_status()

        def gather_selected():
            """Collect the exam's current questions in their display order.

            Returns:
                A tuple ``(name, description, total, questions_with_marks)``
                built from the current form values and ``items``, where
                ``questions_with_marks`` is a list of
                ``(question, marks, parts)`` tuples.
            """
            name = (exam_name.value or "New Exam").strip()
            description = (exam_description.value or "").strip()
            total = int(total_marks_input.value or 0)

            questions_with_marks = []
            for entry in items:
                q = entry["question"]
                widget = entry.get("marks_input")
                marks = int(widget.value or 0) if widget is not None else entry["marks"]
                parts = get_question_parts(q["id"])
                questions_with_marks.append((q, marks, parts))

            return name, description, total, questions_with_marks

        def _safe_filename(name: str) -> str:
            """Strip a string down to characters safe for use in a filename.

            Args:
                name: The raw name to sanitize.

            Returns:
                The sanitized name, or "exam" if nothing safe remains.
            """
            return "".join(c for c in name if c.isalnum() or c in " _-").strip() or "exam"

        def _zip_bytes(files: dict) -> bytes:
            """Package files into an in-memory zip archive.

            Args:
                files: Mapping of filename to file content (str or bytes).

            Returns:
                The zip archive's raw bytes.
            """
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for filename, content in files.items():
                    zf.writestr(filename, content)
            return buf.getvalue()

        def on_preview():
            """Snapshot the current draft and open the exam preview page.

            Preview doesn't require the marks to add up to the full marks
            total (unlike Generate) -- it's meant to be usable at any
            point while still assembling the exam. The draft is written
            to storage (rather than passed in a URL) since it includes
            per-question marks overrides and isn't yet a saved exam.
            """
            if not items:
                ui.notify("Add at least one question first.", color="warning")
                return
            name, description, total, questions_with_marks = gather_selected()
            app.storage.user["exam_draft"] = {
                "name": name,
                "description": description,
                "total_marks": total,
                "include_answers": include_answers.value,
                "items": [
                    {"question_id": q["id"], "marks": marks}
                    for q, marks, _parts in questions_with_marks
                ],
            }
            ui.navigate.to("/exams/preview")

        async def on_download_tex():
            """Build and download the raw LaTeX source for the current exam.

            Always builds the "official" exam paper (blank answer space,
            tick lines, continuation pages at the end). If "Include
            answers" is checked, also builds a matching "solutions"
            source and bundles both (plus any embedded image assets) into
            a single zip; otherwise downloads just the one .tex file (or
            a zip, if it has embedded images).
            """
            if not items:
                ui.notify("Add at least one question first.", color="warning")
                return
            name, description, total, questions_with_marks = gather_selected()
            safe_name = _safe_filename(name)

            tex_source, assets = build_latex(name, description, total, questions_with_marks, mode="official")

            if not include_answers.value:
                # Bundle any embedded images alongside the .tex source so
                # someone compiling this elsewhere (e.g. Overleaf) has
                # everything \includegraphics references, not just the
                # source text.
                files = {f"{safe_name}.tex": tex_source, **assets}
                if assets:
                    ui.download(_zip_bytes(files), filename=f"{safe_name}_tex.zip")
                else:
                    ui.download(tex_source.encode("utf-8"), filename=f"{safe_name}.tex")
            else:
                solutions_tex, solutions_assets = build_latex(name, description, total, questions_with_marks, mode="solutions")
                zip_bytes = _zip_bytes({
                    f"{safe_name}.tex": tex_source,
                    f"{safe_name}_answers.tex": solutions_tex,
                    **assets,
                    **solutions_assets,
                })
                ui.download(zip_bytes, filename=f"{safe_name}_tex.zip")

        async def on_generate():
            """Compile the current exam to PDF and record it.

            Validates the marks add up to the target, compiles the exam
            paper (and, if "Include answers" is checked, a matching
            solutions PDF), saves the exam and its questions to the
            database, then downloads the result -- a single PDF, or a zip
            of the paper + answer key.
            """
            total = selected_total()
            target = int(total_marks_input.value or 0)
            if not items:
                ui.notify("Add at least one question first.", color="warning")
                return
            if total != target:
                # Doesn't block generation -- just a heads-up so the
                # teacher notices before handing the paper out, in case
                # the mismatch wasn't intentional.
                ui.notify(
                    f"Current marks: {total}",
                    color="warning",
                    multi_line=True,
                )

            name, description, total, questions_with_marks = gather_selected()
            with_answers = include_answers.value
            safe_name = _safe_filename(name)

            generate_btn.disable()
            generate_btn.props("loading")
            try:
                try:
                    tex_source, assets = build_latex(name, description, total, questions_with_marks, mode="official")
                    pdf_bytes = await run.io_bound(compile_latex_to_pdf, tex_source, 60, assets)
                    if with_answers:
                        solutions_tex, solutions_assets = build_latex(name, description, total, questions_with_marks, mode="solutions")
                        solutions_pdf = await run.io_bound(compile_latex_to_pdf, solutions_tex, 60, solutions_assets)
                except LatexCompileError as exc:
                    ui.notify(str(exc), color="negative", multi_line=True, close_button=True)
                    return

                # Persist the composed exam so it's recorded in the exam bank.
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                exam_id = add_exam({
                    "Name": name,
                    "Description": description,
                    "Total marks": target,
                    "Status": "Exported (with answers)" if with_answers else "Exported",
                    "Created by": username,
                    "Created at": now,
                })
                for order, (q, marks, _parts) in enumerate(questions_with_marks):
                    add_question_to_exam(exam_id, q["id"], order=order, marks_override=marks)

                # The exam's been recorded -- clear the working selection
                # and any preview draft so the next visit to the Question
                # Bank / Export page starts from a blank slate instead of
                # showing this now-generated exam's picks still ticked.
                app.storage.user["exam_selection"] = []
                app.storage.user.pop("exam_draft", None)

                if not with_answers:
                    ui.download(pdf_bytes, filename=f"{safe_name}.pdf")
                    ui.notify("Exam paper generated.", color="positive")
                else:
                    zip_bytes = _zip_bytes({
                        f"{safe_name}.pdf": pdf_bytes,
                        f"{safe_name}_answers.pdf": solutions_pdf,
                    })
                    ui.download(zip_bytes, filename=f"{safe_name}_with_answers.zip")
                    ui.notify("Exam paper with answers generated.", color="positive")
            finally:
                generate_btn.props(remove="loading")
                refresh_status()

        generate_btn.on_click(on_generate)
        download_tex_btn.on_click(on_download_tex)
        preview_btn.on_click(on_preview)
