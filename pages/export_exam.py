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
    """Build a new exam paper by selecting questions from the question
    bank, giving each one a mark value *for this exam*, and exporting the
    result as a PDF (rendered from a LaTeX template)."""

    # Check login
    if not app.storage.user.get("logged_in"):
        ui.navigate.to("/login")
        return

    username = app.storage.user["username"]

    all_questions = load_questions()
    questions = [q for q in all_questions if q.get("Created by") == username]
    questions.sort(key=lambda q: q["id"])
    for display_id, q in enumerate(questions, start=1):
        q["display_id"] = display_id

    with ui.column().classes("w-full max-w-5xl mx-auto p-6 gap-4"):

        ui.link("← Back to Question Bank", "/questions").classes("text-sm")
        ui.label("Export Exam Paper").classes("text-2xl font-bold")
        ui.label(
            "Select questions from your question bank, set the marks each "
            "one is worth in this exam, then generate a PDF once the "
            "selected marks add up to the full marks total."
        ).classes("text-sm text-grey-600")

        if not questions:
            ui.label("You don't have any questions yet. Create some first.").classes("text-grey-600")
            ui.button("Create New Question", on_click=lambda: ui.navigate.to("/questions/new"))
            return

        # -- Exam settings -----------------------------------------------
        with ui.card().classes("w-full p-4"):
            with ui.row().classes("w-full items-end gap-4"):
                exam_name = ui.input("Exam Name", value="New Exam").classes("w-64")
                total_marks_input = ui.number(
                    "Full Marks (target total)", value=100, min=1
                ).classes("w-56")
                include_answers = ui.checkbox("Include answer key (appendix)")
            exam_description = ui.input("Description (optional)").classes("w-full")

        # -- Selection state -----------------------------------------------
        selected_ids: set = set()
        row_widgets = {}  # question_id -> {"marks_input": ..., "row": ..., "checkbox": ...}

        status_label = ui.label().classes("text-lg font-bold")
        generate_btn = None  # assigned below, referenced by refresh_status()
        download_tex_btn = None

        def selected_total() -> int:
            total = 0
            for qid in selected_ids:
                widget = row_widgets.get(qid)
                if widget:
                    total += int(widget["marks_input"].value or 0)
            return total

        def refresh_status():
            total = selected_total()
            target = int(total_marks_input.value or 0)
            count = len(selected_ids)
            status_label.text = f"Selected: {count} question(s) — {total} / {target} marks"

            ok = count > 0 and total == target
            if ok:
                status_label.classes(replace="text-lg font-bold text-green-700")
            else:
                status_label.classes(replace="text-lg font-bold text-red-600")

            if generate_btn is not None:
                generate_btn.enable() if ok else generate_btn.disable()
            if download_tex_btn is not None:
                download_tex_btn.enable() if count > 0 else download_tex_btn.disable()

        total_marks_input.on_value_change(lambda e: refresh_status())

        # -- Search filter ---------------------------------------------------
        search_input = ui.input("Search by question text or module").classes("w-full")

        # -- Question checklist -----------------------------------------------
        with ui.card().classes("w-full p-0"):
            with ui.row().classes(
                "w-full items-center font-bold border-b px-3 py-2 bg-grey-100"
            ):
                ui.label("").classes("w-10")
                ui.label("ID").classes("w-10")
                ui.label("Question").classes("flex-grow")
                ui.label("Module").classes("w-28")
                ui.label("Default").classes("w-20")
                ui.label("Marks in exam").classes("w-36")

            list_container = ui.column().classes("w-full gap-0")

            def build_rows():
                list_container.clear()
                row_widgets.clear()
                with list_container:
                    for q in questions:
                        qid = q["id"]
                        default_marks = int(q.get("Marks") or 0)

                        with ui.row().classes(
                            "w-full items-center border-b px-3 py-2"
                        ) as row:
                            checkbox = ui.checkbox().classes("w-10")
                            ui.label(str(q["display_id"])).classes("w-10")
                            ui.label(q.get("Question") or "").classes(
                                "flex-grow truncate"
                            )
                            ui.label(q.get("Module") or "—").classes("w-28")
                            ui.label(str(default_marks)).classes("w-20")
                            marks_input = ui.number(
                                value=default_marks, min=0
                            ).classes("w-36")
                            marks_input.disable()

                            def on_toggle(e, qid=qid, marks_input=marks_input):
                                if e.value:
                                    selected_ids.add(qid)
                                    marks_input.enable()
                                else:
                                    selected_ids.discard(qid)
                                    marks_input.disable()
                                refresh_status()

                            checkbox.on_value_change(on_toggle)
                            marks_input.on_value_change(lambda e: refresh_status())

                            row_widgets[qid] = {
                                "checkbox": checkbox,
                                "marks_input": marks_input,
                                "row": row,
                                "question": q,
                            }

            build_rows()

            def apply_search():
                term = (search_input.value or "").strip().lower()
                for q in questions:
                    widget = row_widgets.get(q["id"])
                    if not widget:
                        continue
                    haystack = f"{q.get('Question') or ''} {q.get('Module') or ''}".lower()
                    widget["row"].set_visibility(term in haystack)

            search_input.on_value_change(lambda e: apply_search())

        refresh_status()

        # -- Generate ------------------------------------------------------
        with ui.row().classes("w-full items-center gap-4 mt-2"):
            generate_btn = ui.button("Generate & Download PDF", color="primary")
            download_tex_btn = ui.button("Download LaTeX Source (.tex)", color="secondary")
            generate_btn.disable()
            download_tex_btn.disable()

        def gather_selected():
            """Return (name, description, total, questions_with_marks) built
            from the current selection, in display order."""
            name = (exam_name.value or "New Exam").strip()
            description = (exam_description.value or "").strip()
            total = int(total_marks_input.value or 0)

            questions_with_marks = []
            for q in questions:
                if q["id"] not in selected_ids:
                    continue
                widget = row_widgets[q["id"]]
                marks = int(widget["marks_input"].value or 0)
                parts = get_question_parts(q["id"])
                questions_with_marks.append((q, marks, parts))

            return name, description, total, questions_with_marks

        def build_tex_source():
            name, description, total, questions_with_marks = gather_selected()
            return name, build_latex(
                name, description, total, questions_with_marks,
                include_answers=bool(include_answers.value),
            )

        async def on_download_tex():
            if not selected_ids:
                ui.notify("Select at least one question first.", color="warning")
                return
            name, tex_source = build_tex_source()
            safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip() or "exam"
            ui.download(tex_source.encode("utf-8"), filename=f"{safe_name}.tex")

        async def on_generate():
            total = selected_total()
            target = int(total_marks_input.value or 0)
            if not selected_ids:
                ui.notify("Select at least one question first.", color="warning")
                return
            if total != target:
                ui.notify(
                    f"Selected marks ({total}) must equal the full marks total ({target}).",
                    color="negative",
                )
                return

            name, description, total, questions_with_marks = gather_selected()

            generate_btn.disable()
            generate_btn.props("loading")
            try:
                tex_source = build_latex(
                    name, description, total, questions_with_marks,
                    include_answers=bool(include_answers.value),
                )

                try:
                    pdf_bytes = await run.io_bound(compile_latex_to_pdf, tex_source)
                except LatexCompileError as exc:
                    ui.notify(str(exc), color="negative", multi_line=True, close_button=True)
                    return

                # Persist the composed exam so it's recorded in the exam bank.
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                exam_id = add_exam({
                    "Name": name,
                    "Description": description,
                    "Total marks": target,
                    "Status": "Exported",
                    "Created by": username,
                    "Created at": now,
                })
                for order, (q, marks, _parts) in enumerate(questions_with_marks):
                    add_question_to_exam(exam_id, q["id"], order=order, marks_override=marks)

                safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip() or "exam"
                ui.download(pdf_bytes, filename=f"{safe_name}.pdf")
                ui.notify("Exam paper generated.", color="positive")
            finally:
                generate_btn.props(remove="loading")
                refresh_status()

        generate_btn.on_click(on_generate)
        download_tex_btn.on_click(on_download_tex)
